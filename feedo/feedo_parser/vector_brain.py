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

class VectorBrain:
    def __init__(self, db_path="./lancedb_data"):
        print("🧠 Завантаження ML-моделі (thenlper/gte-large)...")
        self.model = SentenceTransformer('thenlper/gte-large')
        self.db = lancedb.connect(db_path)
        
        self.table_name = "post_vectors"
        
        # ДОДАНО: поле source_type для фільтрації стрічок
        schema = pa.schema([
            pa.field("post_id", pa.int32()),
            pa.field("hash_id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 1024)),
            pa.field("timestamp", pa.float64()),
            pa.field("source_type", pa.string()),
            pa.field("language", pa.string()),
            pa.field("geo", pa.string())
        ])
        
        try:
            self.table = self.db.create_table(self.table_name, schema=schema, exist_ok=True)
            # Перевірка: якщо стара база не має source_type, перестворюємо
            if "source_type" not in self.table.schema.names:
                print("⚠️ Схема LanceDB змінилася (Додано source_type). Перестворюємо таблицю...")
                self.db.drop_table(self.table_name)
                self.table = self.db.create_table(self.table_name, schema=schema)
        except ValueError:
            self.table = self.db.open_table(self.table_name)
            vector_field = self.table.schema.field("vector")
            if not pa.types.is_fixed_size_list(vector_field.type) or vector_field.type.list_size != 1024 or "source_type" not in self.table.schema.names:
                print("⚠️ Схема LanceDB змінилася. Перестворюємо таблицю...")
                self.db.drop_table(self.table_name)
                self.table = self.db.create_table(self.table_name, schema=schema)

        self.executor = ThreadPoolExecutor(max_workers=2)
        
        self.emb_cache = OrderedDict()
        self.max_emb_cache = 10000
        
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
        if len(coerced) != 1024:
            raise ValueError(f"Vector must have exactly 1024 dimensions, got {len(coerced)}")
        return coerced

    def is_gibberish(self, text: str) -> bool:
        if len(text) < 20: 
            return False 
            
        p, lns = Counter(text), float(len(text))
        entropy = -sum(count/lns * math.log2(count/lns) for count in p.values())
        return entropy < 2.0 or entropy > 6.5

    def get_embedding(self, text: str) -> list[float]:
        if text in self.emb_cache:
            self.emb_cache.move_to_end(text)
            return self.emb_cache[text]
        vec = self.model.encode(text, normalize_embeddings=True, show_progress_bar=False).tolist()
        self._cache_emb_set(text, vec)
        return vec

    def get_embeddings_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        results = [None] * len(texts)
        to_compute_idx = []
        to_compute_texts = []
        
        for i, text in enumerate(texts):
            if text in self.emb_cache:
                self.emb_cache.move_to_end(text)
                results[i] = self.emb_cache[text]
            else:
                to_compute_idx.append(i)
                to_compute_texts.append(text)
        
        if to_compute_texts:
            computed = self.model.encode(
                to_compute_texts, 
                batch_size=batch_size, 
                normalize_embeddings=True, 
                show_progress_bar=False
            ).tolist()
            
            for idx, text, vec in zip(to_compute_idx, to_compute_texts, computed):
                results[idx] = vec
                self._cache_emb_set(text, vec)
                
        return results

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

    def add_vector_by_emb(self, post_id: int, hash_id: str, vector: list[float], source_type: str = "native", language: str = "", geo: str = ""):
        # store language and geo for contextual weighting later
        vector = self._coerce_vector(vector)
        self.table.add([{
            "post_id": post_id,
            "hash_id": hash_id,
            "vector": vector,
            "timestamp": time.time(),
            "source_type": source_type,
            "language": language or "",
            "geo": geo or ""
        }])

    async def get_embedding_async(self, text: str) -> list[float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self.get_embedding, text)

    async def get_embeddings_batch_async(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self.get_embeddings_batch, texts, batch_size)

    async def find_duplicate_async(self, text: str, threshold: float = 0.95, hours: int = 24) -> str | None:
        vector = await self.get_embedding_async(text)
        return self.find_duplicate_by_vector(vector, threshold, hours)

    async def add_vector_async(self, post_id: int, hash_id: str, text: str, source_type: str = "native", language: str = "", geo: str = ""):
        vector = await self.get_embedding_async(text)
        self.add_vector_by_emb(post_id, hash_id, vector, source_type, language=language, geo=geo)

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