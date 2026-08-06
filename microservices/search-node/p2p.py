import httpx
import asyncio
import os
import time
import numpy as np
from vector_service import VectorBrain

class P2PNetwork:
    def __init__(self, vector_brain: VectorBrain, host: str, port: int):
        self.vector_brain = vector_brain
        self.host = host
        self.port = port
        
        base_url = os.environ.get("PUBLIC_API_URL")
        if base_url:
            self.my_url = base_url.rstrip('/')
        else:
            self.my_url = f"http://{host}:{port}"
        
        peers_env = os.environ.get("KNOWN_PEERS", "")
        if peers_env:
            self.known_peers = set([p.strip() for p in peers_env.split(",") if p.strip()])
        else:
            self.known_peers = set()
            
        if self.my_url in self.known_peers:
            self.known_peers.remove(self.my_url)
            
        self.client = httpx.AsyncClient(timeout=5.0)

        # Phase 1.5: Event-driven centroid update tracking
        self._last_broadcasted_centroids: list[list[float]] = []
        self._last_broadcast_time: float = 0.0
        self._event_driven_enabled = os.getenv("EVENT_DRIVEN_CENTROIDS", "true").lower() in ("1", "true", "yes")
        self._centroid_similarity_threshold = float(os.getenv("CENTROID_CHANGE_THRESHOLD", "0.9"))
        print(f"[P2P] Event-driven centroids: {'ENABLED' if self._event_driven_enabled else 'DISABLED'} "
              f"(similarity_threshold={self._centroid_similarity_threshold})")

    def _centroids_changed_significantly(self, new_centroids: list[list[float]]) -> bool:
        """
        Compare new centroids against the last broadcasted set.
        Uses average max cosine similarity between old/new centroid sets.
        Returns True if centroids have changed significantly enough to warrant broadcast.
        """
        if not self._last_broadcasted_centroids and not new_centroids:
            return False # Both empty, no change
        if not self._last_broadcasted_centroids or not new_centroids:
            return True  # first broadcast or empty data — always send

        old_np = np.array(self._last_broadcasted_centroids, dtype=np.float64)
        new_np = np.array(new_centroids, dtype=np.float64)

        if old_np.shape != new_np.shape:
            return True  # different number of clusters — significant change

        old_norms = np.linalg.norm(old_np, axis=1)
        new_norms = np.linalg.norm(new_np, axis=1)

        # For each new centroid, find the most similar old centroid
        # Average the max similarities across all new centroids
        similarities = []
        for i, new_c in enumerate(new_np):
            # Cosine similarity with all old centroids
            sims = np.dot(old_np, new_c) / (old_norms * new_norms[i] + 1e-10)
            similarities.append(float(np.max(sims)))

        avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0
        changed = avg_similarity < self._centroid_similarity_threshold
        if changed:
            print(f"🔄 Centroid drift detected: avg_similarity={avg_similarity:.3f} < threshold={self._centroid_similarity_threshold}")
        return changed

    async def _do_broadcast(self, centroids: list[list[float]], reason: str = "periodic"):
        """Send centroids to all known peers and update local tracking."""
        cluster_ids = [f"cluster_{i}" for i in range(len(centroids))]
        payload = {
            "peer_id": self.my_url,
            "centroids": centroids,
            "cluster_ids": cluster_ids,
        }

        for peer in self.known_peers:
            try:
                resp = await self.client.post(f"{peer}/p2p/handshake", json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    # Peer Exchange: learn about other nodes from the response
                    for new_peer in data.get("peers", []):
                        if new_peer != self.my_url and new_peer not in self.known_peers:
                            self.known_peers.add(new_peer)
                            print(f"🔗 Discovered new peer via exchange: {new_peer}")
                    print(f"📡 Sent centroids to {peer} ({reason})")
            except Exception:
                pass  # Peer might be offline

        # Update tracking
        self._last_broadcasted_centroids = centroids
        self._last_broadcast_time = time.time()

    async def broadcast_centroids_loop(self):
        """Periodically runs clustering and broadcasts centroids to peers.
        Phase 1.5: Also checks for event-driven updates between timer ticks."""
        print("🌐 Starting P2P Gossip Loop with event-driven centroid detection...")
        cycle_interval = 60 * 10  # 10 minutes base cycle
        check_interval = 10  # Check every 10 seconds for event-driven updates

        while True:
            elapsed_since_last_check = 0.0
            while elapsed_since_last_check < cycle_interval:
                # Event-driven check: if we've accumulated enough new vectors and
                # centroids have changed significantly, broadcast immediately.
                if self._event_driven_enabled:
                    inserts_since = self.vector_brain.inserts_since_centroids_update
                    if inserts_since == 0 and self.vector_brain._my_centroids_cache is None:
                        # Centroid cache was invalidated (threshold hit in add_vector_by_emb)
                        # — centroids may have changed. Use _get_my_centroids() to repopulate cache.
                        new_centroids = self.vector_brain._get_my_centroids(n_clusters=20)
                        if new_centroids is not None and self._centroids_changed_significantly(new_centroids):
                            await self._do_broadcast(new_centroids, reason="event-driven")

                await asyncio.sleep(check_interval)
                elapsed_since_last_check += check_interval

            # Periodic broadcast
            centroids = self.vector_brain.compute_centroids(n_clusters=20)
            if centroids is not None:
                await self._do_broadcast(centroids, reason="periodic")

    async def federated_search(self, query_vector: list[float], query_text: str, ttl: int, top_k: int = 10) -> list[dict]:
        """Routes the query to top peers and aggregates results."""
        if ttl <= 0:
            return []
            
        # 1. Find the best peers to route to
        target_peers = self.vector_brain.route_query(query_vector, top_k=top_k)
        
        results = []
        tasks = []
        
        payload = {
            "query": query_text,
            "ttl": ttl - 1
        }
        
        for peer in target_peers:
            if peer == self.my_url:
                continue
                
            async def fetch(p):
                try:
                    resp = await self.client.post(f"{p}/p2p/search", json=payload)
                    if resp.status_code == 200:
                        return resp.json().get("results", [])
                except Exception as e:
                    pass
                return []
                
            tasks.append(fetch(peer))
            
        if tasks:
            peer_results = await asyncio.gather(*tasks)
            for r_list in peer_results:
                results.extend(r_list)
                
        return results
