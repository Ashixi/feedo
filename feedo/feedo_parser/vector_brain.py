import math
import time
import asyncio
import json
from collections import Counter, OrderedDict
import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from sklearn.cluster import KMeans
from sklearn.neighbors import NearestNeighbors

import requests
import torch
import io
from PIL import Image

class VectorBrain:
    def __init__(self, db_path="./lancedb_data"):
        print("🧠 Завантаження ML-моделі (intfloat/multilingual-e5-small) через ONNX Runtime...")
        self.model = SentenceTransformer('intfloat/multilingual-e5-small', backend="onnx")
        print("👁️ Завантаження Multimodal-моделі (clip-ViT-B-32)...")
        self.image_model = SentenceTransformer('clip-ViT-B-32', model_kwargs={"torch_dtype": torch.float16})
        self.db = lancedb.connect(db_path)

        
        self.table_name = "post_vectors"
        
        # ДОДАНО: поле source_type для фільтрації стрічок
        schema = pa.schema([
            pa.field("post_id", pa.int32()),
            pa.field("hash_id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 384)),
            pa.field("image_vector", pa.list_(pa.float32(), 512)),
            pa.field("timestamp", pa.float64()),
            pa.field("source_type", pa.string()),
            pa.field("item_type", pa.string()),
            pa.field("language", pa.string()),
            pa.field("geo", pa.string()),
            pa.field("relay_url", pa.string())
        ])
        
        try:
            self.table = self.db.create_table(self.table_name, schema=schema, exist_ok=True)
            if "item_type" not in self.table.schema.names or "relay_url" not in self.table.schema.names or "image_vector" not in self.table.schema.names:
                print("⚠️ Схема LanceDB змінилася (Додано item_type/image_vector). Перестворюємо таблицю...")
                self.db.drop_table(self.table_name)
                self.table = self.db.create_table(self.table_name, schema=schema)
        except ValueError:
            self.table = self.db.open_table(self.table_name)
            vector_field = self.table.schema.field("vector")
            if not pa.types.is_fixed_size_list(vector_field.type) or vector_field.type.list_size != 384 or "item_type" not in self.table.schema.names:
                print("⚠️ Схема LanceDB змінилася. Перестворюємо таблицю...")
                self.db.drop_table(self.table_name)
                self.table = self.db.create_table(self.table_name, schema=schema)

        self.executor = ThreadPoolExecutor(max_workers=2)
        
        self.emb_cache = OrderedDict()
        self.max_emb_cache = 10000
        
        self.inserts_since_optimize = 0
        
        self.search_cache = {}
        self.max_search_cache = 2000
        
        # --- Stage V: Supernode Global Knowledge Map ---
        # Stores global centroids from other supernodes
        # Format: [{"centroid": [float, ...], "peer_id": str, "cluster_id": str}]
        self.global_knowledge_map = []
        self.nn_model = NearestNeighbors(n_neighbors=3, metric="cosine")
        self.nn_fitted = False
        
        # Tracking for event-based updates
        self.last_cluster_post_count = 0

    def _cache_emb_set(self, text: str, vec: list[float]):
        self.emb_cache[text] = vec
        self.emb_cache.move_to_end(text)
        while len(self.emb_cache) > self.max_emb_cache:
            self.emb_cache.popitem(last=False)

    def _coerce_vector(self, vector: list[float] | str | tuple) -> list[float]:
        if isinstance(vector, str):
            try:
                vector = json.loads(vector)
            except Exception as e:
                raise ValueError(f"Vector must be a list of floats, got string: {e}")

        if not isinstance(vector, (list, tuple)):
            raise ValueError(f"Vector must be a list of floats, got {type(vector)!r}")

        coerced = [float(v) for v in vector]
        if len(coerced) != 384:
            raise ValueError(f"Vector must have exactly 384 dimensions, got {len(coerced)}")
        return coerced

    def is_gibberish(self, text: str) -> bool:
        if len(text) < 20: 
            return False 
            
        p, lns = Counter(text), float(len(text))
        entropy = -sum(count/lns * math.log2(count/lns) for count in p.values())
        return entropy < 2.0 or entropy > 6.5

    def chunk_text(self, text: str, max_words: int = 350) -> list[str]:
        words = text.split()
        if len(words) <= max_words:
            return [text]
        return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]

    def get_embedding(self, text: str, is_query: bool = False) -> list[float]:
        if text in self.emb_cache:
            self.emb_cache.move_to_end(text)
            return self.emb_cache[text]
        prefix = "query: " if is_query else "passage: "
        vec = self.model.encode(prefix + text, normalize_embeddings=True, show_progress_bar=False).tolist()
        self._cache_emb_set(text, vec)
        return vec

    def get_embeddings_batch(self, texts: list[str], batch_size: int = 32) -> list[list[list[float]]]:
        results = []
        all_chunks_flat = []
        chunk_counts = []
        
        for text in texts:
            chunks = self.chunk_text(text)
            chunk_counts.append(len(chunks))
            all_chunks_flat.extend(chunks)
            
        computed_flat = [None] * len(all_chunks_flat)
        to_compute_idx = []
        to_compute_texts = []
        
        for i, chunk in enumerate(all_chunks_flat):
            if chunk in self.emb_cache:
                self.emb_cache.move_to_end(chunk)
                computed_flat[i] = self.emb_cache[chunk]
            else:
                to_compute_idx.append(i)
                to_compute_texts.append(chunk)
                
        if to_compute_texts:
            prefixed_texts = ["passage: " + t for t in to_compute_texts]
            computed = self.model.encode(
                prefixed_texts, 
                batch_size=batch_size, 
                normalize_embeddings=True, 
                show_progress_bar=False
            ).tolist()
            
            for idx, chunk, vec in zip(to_compute_idx, to_compute_texts, computed):
                computed_flat[idx] = vec
                self._cache_emb_set(chunk, vec)
                
        offset = 0
        for count in chunk_counts:
            results.append(computed_flat[offset:offset + count])
            offset += count
            
        return results

    def optimize_index(self):
        try:
            if len(self.table) >= 500:
                print("⚡ Оптимізація LanceDB: Створення INT8 індексу...")
                self.table.create_index(metric="cosine", vector_column_name="vector", num_partitions=256, num_sub_vectors=96, replace=True)
                print("✅ Індекс успішно створено (Квантизація увімкнена).")
        except Exception as e:
            print(f"⚠️ Не вдалося створити індекс LanceDB: {e}")

    def find_duplicate_by_vector(self, vector: list[float], threshold: float = 0.95, hours: int = 24) -> str | None:
        cutoff_time = time.time() - (hours * 3600)
        try:
            results = self.table.search(vector).where(f"timestamp >= {cutoff_time}").limit(1).to_list()
            if results:
                best_match = results[0]
                similarity = 1.0 - (best_match["_distance"] / 2.0)
                if similarity >= threshold:
                    return best_match.get("hash_id")
        except Exception as e:
            print(f"⚠️ Помилка LanceDB: {e}")
        return None

    def route_query(self, query_vector: list[float], top_k: int = 3) -> list[str]:
        """
        Phase 4: Semantic Routing Validation.
        Determines the best peer supernodes to route this semantic query to,
        based on their known Global Knowledge Map centroids.
        For now, if the global map is empty, returns an empty list, 
        thus avoiding old legacy P2P flooding.
        """
        if not hasattr(self, 'global_map') or not self.global_map:
            return []
            
        import numpy as np
        query_np = np.array(query_vector)
        
        peer_distances = []
        for peer_id, centroids in self.global_map.items():
            if not centroids:
                continue
            
            # Find the minimum distance from query to any centroid of this peer
            min_dist = float('inf')
            for c in centroids:
                c_np = np.array(c)
                # Cosine distance
                dist = 1.0 - (np.dot(query_np, c_np) / (np.linalg.norm(query_np) * np.linalg.norm(c_np)))
                if dist < min_dist:
                    min_dist = dist
                    
            peer_distances.append((peer_id, min_dist))
            
        # Sort by closest distance
        peer_distances.sort(key=lambda x: x[1])
        
        # Return top_k peers
        return [p[0] for p in peer_distances[:top_k]]

    def add_vector_by_emb(self, post_id: int, hash_id: str, vector: list[float], source_type: str = "native", item_type: str = "post", language: str = "", geo: str = "", relay_url: str = "", image_vector: list[float] = None):
        # store language, geo, relay_url for contextual weighting later
        vector = self._coerce_vector(vector)
        if image_vector is None:
            image_vector = [0.0] * 512
            
        self.table.add([{
            "post_id": post_id,
            "hash_id": hash_id,
            "vector": vector,
            "image_vector": image_vector,
            "timestamp": time.time(),
            "source_type": source_type,
            "item_type": item_type,
            "language": language or "",
            "geo": geo or "",
            "relay_url": relay_url or ""
        }])
        
        self.inserts_since_optimize += 1
        if self.inserts_since_optimize >= 500:
            self.inserts_since_optimize = 0
            self.executor.submit(self.optimize_index)

    def get_image_embedding(self, image_url: str) -> list[float]:
        try:
            response = requests.get(image_url, timeout=5.0)
            response.raise_for_status()
            image = Image.open(io.BytesIO(response.content)).convert("RGB")
            vec = self.image_model.encode(image).tolist()
            return vec
        except Exception as e:
            print(f"⚠️ Помилка обробки зображення {image_url}: {e}")
            return None

    async def get_image_embedding_async(self, image_url: str) -> list[float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self.get_image_embedding, image_url)

    async def get_embedding_async(self, text: str, is_query: bool = False) -> list[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.get_embedding, text, is_query)

    async def get_embeddings_batch_async(self, texts: list[str], batch_size: int = 32) -> list[list[list[float]]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.get_embeddings_batch, texts, batch_size)

    async def find_duplicate_async(self, text: str, threshold: float = 0.95, hours: int = 24) -> str | None:
        vector = await self.get_embedding_async(text)
        return self.find_duplicate_by_vector(vector, threshold, hours)

    async def add_vector_async(self, post_id: int, hash_id: str, text: str, source_type: str = "native", item_type: str = "post", language: str = "", geo: str = ""):
        vector = await self.get_embedding_async(text)
        self.add_vector_by_emb(post_id, hash_id, vector, source_type, item_type=item_type, language=language, geo=geo)

    async def update_user_vector_async(self, current_vector: list[float] | None, post_text: str, weight: float = 0.2) -> list[float]:
        new_interest = await self.get_embedding_async(post_text)
        if not current_vector:
            return new_interest
        updated = [(1 - weight) * c + weight * n for c, n in zip(current_vector, new_interest)]
        return updated

    def get_anti_bubble_feed(self, user_vector: list[float], limit: int = 50, source_type: str = "main", user_languages: list[str] | None = None, user_geo: str | None = None) -> dict:
        if not user_vector:
            return {"relevant": [], "discovery": []}

        vec_tuple = tuple(round(v, 4) for v in user_vector) 
        cache_key = (vec_tuple, source_type)
        now = time.time()
        
        if cache_key in self.search_cache:
            cache_time, cached_res = self.search_cache[cache_key]
            if now - cache_time < 300: 
                return cached_res

        try:
            query = self.table.search(user_vector)
            
            # Фільтруємо джерела прямо в векторній БД
            # 'main' = native + rss + p2p_relay
            # 'general' = native + rss (news from feeds + Feedo)
            if source_type == "main":
                query = query.where("source_type IN ('native', 'rss', 'p2p_relay')")
            elif source_type == "general":
                query = query.where("source_type IN ('native', 'rss')")
            else:
                query = query.where(f"source_type = '{source_type}'")
                
            results = query.limit(200).to_list()
        except Exception as e:
            print(f"⚠️ Помилка LanceDB при пошуку: {e}")
            return {"relevant": [], "discovery": []}
        
        relevant_ids = []
        discovery_ids = []
        
        rel_target = int(limit * 0.7)
        disc_target = int(limit * 0.3)
        
        # Apply contextual language and geo multipliers per result
        user_langs = [l.lower() for l in (user_languages or [])]
        for res in results:
            hash_id = res.get("hash_id")
            if not hash_id:
                continue
            similarity = 1.0 - (res["_distance"] / 2.0)

            lang = (res.get("language") or "").lower()
            geo = (res.get("geo") or "")

            # language weight: prefer user's known languages, penalize unknown
            if user_langs:
                if lang in user_langs:
                    lang_w = 1.0
                elif not lang:
                    lang_w = 0.9
                else:
                    lang_w = 0.5
            else:
                lang_w = 1.0

            # geo weight: same geo -> slight boost, otherwise neutral/reduced
            if user_geo and geo:
                if geo == user_geo:
                    geo_w = 1.2
                elif geo.split("-")[0] == user_geo.split("-")[0]:
                    geo_w = 1.05
                else:
                    geo_w = 0.6
            else:
                geo_w = 1.0

            score = similarity * lang_w * geo_w

            if score > 0.65:
                if len(relevant_ids) < rel_target:
                    relevant_ids.append((hash_id, score))
            elif 0.2 < score <= 0.65:
                if len(discovery_ids) < disc_target:
                    discovery_ids.append((hash_id, score))
                    
            if len(relevant_ids) >= rel_target and len(discovery_ids) >= disc_target:
                break

        # strip scores before returning; callers may re-query DB for context/hotness
        final_res = {"relevant": relevant_ids, "discovery": discovery_ids}
        
        if len(self.search_cache) >= self.max_search_cache:
            self.search_cache.clear()
        self.search_cache[cache_key] = (now, final_res)
        
        return final_res

    # --- Stage V: Supernode AI Scaling ---

    def compute_centroids(self, n_clusters: int = 10) -> list[list[float]]:
        """
        Computes KMeans centroids for all local vectors.
        Returns a list of centroids (1024-dimensional vectors).
        """
        try:
            # Fetch all vectors (in a real system, you might sample or batch if > memory)
            # We'll limit to a large number just in case
            all_records = self.table.search().limit(100000).to_list()
            if not all_records:
                return []
                
            vectors = np.array([r["vector"] for r in all_records])
            
            # Update tracking for event-based logic
            self.last_cluster_post_count = len(vectors)
            
            # If we have fewer vectors than clusters, adjust k
            k = min(n_clusters, len(vectors))
            if k == 0:
                return []
                
            kmeans = KMeans(n_clusters=k, random_state=42, n_init="auto")
            kmeans.fit(vectors)
            
            centroids = kmeans.cluster_centers_.tolist()
            return centroids
        except Exception as e:
            print(f"⚠️ Error computing centroids: {e}")
            return []

    def update_global_map(self, peer_id: str, centroids: list[list[float]], cluster_ids: list[str]):
        """
        Updates the global knowledge map with centroids from a specific supernode.
        """
        # Remove old centroids for this peer
        self.global_knowledge_map = [c for c in self.global_knowledge_map if c["peer_id"] != peer_id]
        
        # Add new centroids
        for centroid, cid in zip(centroids, cluster_ids):
            self.global_knowledge_map.append({
                "centroid": centroid,
                "peer_id": peer_id,
                "cluster_id": cid
            })
            
        # Rebuild the NearestNeighbors model for fast routing
        if self.global_knowledge_map:
            X = np.array([c["centroid"] for c in self.global_knowledge_map])
            n_neighbors = min(3, len(X))
            self.nn_model = NearestNeighbors(n_neighbors=n_neighbors, metric="cosine")
            self.nn_model.fit(X)
            self.nn_fitted = True

    def route_query(self, query_vector: list[float], top_k: int = 3) -> list[str]:
        """
        Returns the top_k peer_ids of Supernodes that have centroids closest to the query.
        Uses NearestNeighbors (ANN) for fast routing.
        """
        if not self.nn_fitted or not self.global_knowledge_map:
            return []
            
        vec_np = np.array([query_vector])
        
        try:
            n_neighbors = min(top_k, len(self.global_knowledge_map))
            distances, indices = self.nn_model.kneighbors(vec_np, n_neighbors=n_neighbors)
            
            target_peers = []
            for idx in indices[0]:
                peer_id = self.global_knowledge_map[idx]["peer_id"]
                if peer_id not in target_peers:
                    target_peers.append(peer_id)
            return target_peers
        except Exception as e:
            print(f"⚠️ Error routing query: {e}")
            return []