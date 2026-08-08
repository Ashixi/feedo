import math
import time
import asyncio
import os
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
        print("[SEARCH] Loading ML model (intfloat/multilingual-e5-small) via SentenceTransformers...")
        self.model = SentenceTransformer('intfloat/multilingual-e5-small')
        print("[SEARCH] Loading Multimodal model (clip-ViT-B-32)...")
        self.image_model = SentenceTransformer('clip-ViT-B-32')
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
            pa.field("relay_url", pa.string()),
            pa.field("author", pa.string()),
            pa.field("text", pa.string()),
            pa.field("metadata", pa.string())
        ])
        
        try:
            self.table = self.db.create_table(self.table_name, schema=schema, exist_ok=True)
        except Exception:
            self.table = self.db.open_table(self.table_name)

        cpu_count = os.cpu_count() or 4
        self.executor = ThreadPoolExecutor(max_workers=cpu_count)
        print(f"[SEARCH] ThreadPoolExecutor with {cpu_count} workers")
        
        # Embedding cache: LRU OrderedDict with TTL (1 hour)
        # Value format: (vector, timestamp)
        self.emb_cache = OrderedDict()
        self.max_emb_cache = 100000
        self.emb_cache_ttl = 3600  # 1 hour in seconds
        
        self.inserts_since_optimize = 0
        
        # Search cache: dict with TTL (5 minutes)
        # Value format: (results, timestamp)
        self.search_cache = {}
        self.max_search_cache = 20000
        self.search_cache_ttl = 300  # 5 minutes in seconds
        
        # --- Stage V: Supernode Global Knowledge Map ---
        # Stores global centroids from other supernodes
        # Format: [{"centroid": [float, ...], "peer_id": str, "cluster_id": str}]
        self.global_knowledge_map = []
        self.nn_model = NearestNeighbors(n_neighbors=3, metric="cosine")
        self.nn_fitted = False
        
        # Tracking for event-based updates
        self.last_cluster_post_count = 0
        self.default_vector = None

        # --- Phase 1.5: Semantic Sharding ---
        # Cached local centroids for is_my_shard() decisions
        self._my_centroids_cache = None       # list[list[float]] | None
        self._my_centroids_ts = 0.0           # timestamp of last computation
        self._centroids_cache_ttl = int(os.getenv("SHARD_CENTROID_CACHE_TTL", "600"))  # 10 min
        self.inserts_since_centroids_update = 0
        self._centroids_update_threshold = int(os.getenv("SHARD_CENTROID_UPDATE_THRESHOLD", "100"))
        self._sharding_enabled = os.getenv("SEMANTIC_SHARDING_ENABLED", "true").lower() in ("1", "true", "yes")
        print(f"[SEARCH] Semantic sharding: {'ENABLED' if self._sharding_enabled else 'DISABLED'} "
              f"(centroid_cache_ttl={self._centroids_cache_ttl}s, update_threshold={self._centroids_update_threshold})")
        
    async def update_default_vector(self):
        def run_query():
            try:
                # Query top 100 vectors directly from LanceDB table
                return self.table.search().limit(100).to_list()
            except Exception as e:
                print(f"Error querying LanceDB for default vector: {e}")
                return []
                
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(self.executor, run_query)
        
        vectors = [r["vector"] for r in results if "vector" in r and r["vector"] is not None]
        if vectors:
            dim = len(vectors[0])
            avg_vec = []
            for i in range(dim):
                col_sum = sum(v[i] for v in vectors)
                avg_vec.append(col_sum / len(vectors))
            self.default_vector = avg_vec
            print(f"Calculated default vector of length {len(avg_vec)} from {len(vectors)} posts.")
        else:
            print("No vectors found in LanceDB to calculate default vector.")

    def _cache_emb_get(self, text: str) -> list[float] | None:
        """Get cached embedding if present and not expired."""
        if text in self.emb_cache:
            cached = self.emb_cache[text]
            if isinstance(cached, tuple) and len(cached) == 2:
                vec, ts = cached
                if time.time() - ts < self.emb_cache_ttl:
                    self.emb_cache.move_to_end(text)
                    return vec
                else:
                    # Expired, remove
                    del self.emb_cache[text]
            else:
                # Legacy format: just vector, no TTL — treat as valid
                self.emb_cache.move_to_end(text)
                return cached
        return None

    def _cache_emb_set(self, text: str, vec: list[float]):
        self.emb_cache[text] = (vec, time.time())
        self.emb_cache.move_to_end(text)
        while len(self.emb_cache) > self.max_emb_cache:
            self.emb_cache.popitem(last=False)
    
    def _cache_search_get(self, cache_key: str) -> list | None:
        """Get cached search result if present and not expired."""
        if cache_key in self.search_cache:
            results, ts = self.search_cache[cache_key]
            if time.time() - ts < self.search_cache_ttl:
                return results
            else:
                del self.search_cache[cache_key]
        return None
    
    def _cache_search_set(self, cache_key: str, results: list):
        self.search_cache[cache_key] = (results, time.time())
        # Evict oldest if over limit
        while len(self.search_cache) > self.max_search_cache:
            oldest_key = next(iter(self.search_cache))
            del self.search_cache[oldest_key]

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
        import re
        clean_text = re.sub(r'https?://\S+', '', text)
        clean_text = re.sub(r'nostr:\S+', '', clean_text)
        clean_text = re.sub(r':\w+:', '', clean_text)
        clean_text = clean_text.strip()
        
        # If text is entirely empty after cleaning links/emojis, it's gibberish
        if len(clean_text) < 1:
            return True
            
        p, lns = Counter(clean_text), float(len(clean_text))
        if lns == 0: return True
        
        # Only apply entropy (spam/repetition) checks on longer texts.
        # Short texts (like "GM") naturally have very low entropy.
        if lns > 20:
            entropy = -sum(count/lns * math.log2(count/lns) for count in p.values())
            return entropy < 1.5 or entropy > 6.5
            
        return False

    def clean_text_for_embedding(self, text: str) -> str:
        import re
        clean = re.sub(r'https?://\S+', '', text)
        clean = re.sub(r'nostr:\S+', '', clean)
        clean = re.sub(r':\w+:', '', clean)
        return clean.strip() or text  # Fallback to original if empty

    def chunk_text(self, text: str, max_words: int = 350) -> list[str]:
        text = self.clean_text_for_embedding(text)
        words = text.split()
        if len(words) <= max_words:
            return [text]
        return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]

    def get_embedding(self, text: str, is_query: bool = False) -> list[float]:
        clean_text = self.clean_text_for_embedding(text)
        cached = self._cache_emb_get(clean_text)
        if cached is not None:
            return cached
        prefix = "query: " if is_query else "passage: "
        vec = self.model.encode(prefix + clean_text, normalize_embeddings=True, show_progress_bar=False).tolist()
        self._cache_emb_set(clean_text, vec)
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
            cached = self._cache_emb_get(chunk)
            if cached is not None:
                computed_flat[i] = cached
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

    def add_vector_by_emb(self, post_id: int, hash_id: str, vector: list[float], source_type: str = "native", item_type: str = "post", language: str = "", geo: str = "", relay_url: str = "", image_vector: list[float] = None, author: str = "", text: str = "", metadata: str = ""):
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
            "language": language,
            "geo": geo,
            "relay_url": relay_url,
            "author": author,
            "text": text,
            "metadata": metadata
        }])
        
        self.inserts_since_optimize += 1
        if self.inserts_since_optimize >= 500:
            self.inserts_since_optimize = 0
            self.executor.submit(self.optimize_index)

        # Invalidate centroid cache after threshold for event-driven updates
        self.inserts_since_centroids_update += 1
        if self.inserts_since_centroids_update >= self._centroids_update_threshold:
            self.inserts_since_centroids_update = 0
            self._my_centroids_cache = None

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

    async def add_vector_async(self, post_id: int, hash_id: str, text: str, source_type: str = "native", item_type: str = "post", language: str = "", geo: str = "", image_vector: list[float] = None, relay_url: str = None, author: str = "", metadata: str = ""):
        if not language and text and len(text.strip()) > 5:
            try:
                from langdetect import detect
                loop = asyncio.get_event_loop()
                language = await loop.run_in_executor(self.executor, detect, text)
            except Exception:
                pass
                
        vector = [0.0] * 384
        if text:
            clean = self.clean_text_for_embedding(text)
            if self.is_gibberish(clean):
                return
                
            loop = asyncio.get_event_loop()
            prefixed = "passage: " + clean
            
            computed = await loop.run_in_executor(
                self.executor,
                lambda: self.model.encode([prefixed], normalize_embeddings=True)[0]
            )
            vector = computed.tolist()
            self._cache_emb_set(clean, vector)
            
        self.add_vector_by_emb(post_id, hash_id, vector, source_type, item_type=item_type, language=language, geo=geo, image_vector=image_vector, relay_url=relay_url, author=author, text=text, metadata=metadata)

    async def add_image_vector_async(self, post_id: int, hash_id: str, image_url: str, symmetric_key: str = None, source_type: str = "native", item_type: str = "image", author: str = "", metadata: str = ""):
        loop = asyncio.get_event_loop()
        
        def process_image():
            response = requests.get(image_url, timeout=10.0)
            response.raise_for_status()
            raw_data = response.content
            
            if symmetric_key:
                import binascii
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                key_bytes = binascii.unhexlify(symmetric_key)
                if len(raw_data) < 28:
                    raise ValueError("Data too short to be AES-GCM encrypted")
                nonce = raw_data[:12]
                tag = raw_data[-16:]
                ciphertext = raw_data[12:-16]
                cipher = Cipher(algorithms.AES(key_bytes), modes.GCM(nonce, tag))
                decryptor = cipher.decryptor()
                raw_data = decryptor.update(ciphertext) + decryptor.finalize()
                
            image = Image.open(io.BytesIO(raw_data)).convert("RGB")
            return self.image_model.encode(image).tolist()
            
        try:
            image_vector = await loop.run_in_executor(self.executor, process_image)
            vector = [0.0] * 384
            self.add_vector_by_emb(
                post_id=post_id,
                hash_id=hash_id,
                vector=vector,
                source_type=source_type,
                item_type=item_type,
                author=author,
                image_vector=image_vector,
                metadata=metadata
            )
        except Exception as e:
            print(f"⚠️ Помилка векторизації зображення {hash_id}: {e}")

    async def update_user_vector_async(self, current_vector: list[float] | None, post_text: str, weight: float = 0.2) -> list[float]:
        new_interest = await self.get_embedding_async(post_text)
        if not current_vector:
            return new_interest
        updated = [(1 - weight) * c + weight * n for c, n in zip(current_vector, new_interest)]
        return updated

    def delete_vector(self, hash_id: str):
        try:
            self.table.delete(f"hash_id = '{hash_id}'")
        except Exception as e:
            print(f"⚠️ Error deleting from LanceDB: {e}")

    async def delete_vector_async(self, hash_id: str):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, self.delete_vector, hash_id)



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

    # --- Phase 1.5: Semantic Sharding Methods ---

    def _get_my_centroids(self, n_clusters: int = 20) -> list[list[float]]:
        """
        Returns cached local centroids, recomputing if stale.
        This is a lightweight alternative to compute_centroids() that uses caching.
        """
        now = time.time()
        cache_valid = (
            self._my_centroids_cache is not None
            and (now - self._my_centroids_ts) < self._centroids_cache_ttl
        )
        if cache_valid:
            return self._my_centroids_cache

        centroids = self.compute_centroids(n_clusters=n_clusters)
        self._my_centroids_cache = centroids
        self._my_centroids_ts = now
        self.inserts_since_centroids_update = 0
        return centroids

    def is_my_shard(self, vector: list[float]) -> bool:
        """
        Determines whether a given vector belongs to this node's semantic shard.

        Algorithm:
        1. Get my local centroids (cached, recomputed lazily).
        2. Compute min cosine distance from vector to my centroids.
        3. Get foreign centroids from global_knowledge_map.
        4. If no foreign centroids → True (fallback: solo node indexes everything).
        5. Compute min cosine distance to foreign centroids.
        6. Return True if my closest centroid is nearer than the closest foreign centroid.

        Feature flag: SEMANTIC_SHARDING_ENABLED=false always returns True.
        """
        if not self._sharding_enabled:
            return True

        vector_np = np.array(vector, dtype=np.float64)
        v_norm = np.linalg.norm(vector_np)
        if v_norm == 0.0:
            return True  # degenerate vector, keep locally

        my_centroids = self._get_my_centroids()
        if not my_centroids:
            # No local centroids yet (empty table) — index locally
            return True

        my_np = np.array(my_centroids, dtype=np.float64)
        my_norms = np.linalg.norm(my_np, axis=1)
        # Cosine similarity: dot / (||v|| * ||c_i||)
        my_similarities = np.dot(my_np, vector_np) / (v_norm * my_norms + 1e-10)
        my_min_similarity = float(np.max(my_similarities))

        # Check foreign centroids
        if not self.global_knowledge_map:
            # No peer data yet — index locally (safe default)
            return True

        foreign_centroids = np.array([c["centroid"] for c in self.global_knowledge_map], dtype=np.float64)
        foreign_norms = np.linalg.norm(foreign_centroids, axis=1)
        foreign_similarities = np.dot(foreign_centroids, vector_np) / (v_norm * foreign_norms + 1e-10)
        foreign_min_similarity = float(np.max(foreign_similarities))

        # Higher cosine similarity = closer in semantic space
        return my_min_similarity >= foreign_min_similarity

    def route_vector_to_node(self, vector: list[float]) -> str | None:
        """
        Returns the peer_id (URL) of the node whose centroid is closest to the vector.
        Uses the NearestNeighbors model built by update_global_map().
        Returns None if no global knowledge map is available.

        This is called ONLY when is_my_shard() returns False, to determine
        where to forward the vector.
        """
        if not self.nn_fitted or not self.global_knowledge_map:
            return None

        vec_np = np.array([vector], dtype=np.float64)
        try:
            distances, indices = self.nn_model.kneighbors(vec_np, n_neighbors=1)
            idx = indices[0][0]
            return self.global_knowledge_map[idx]["peer_id"]
        except Exception as e:
            print(f"⚠️ Error routing vector to node: {e}")
            return None
