import httpx
import asyncio
from vector_service import VectorBrain

class P2PNetwork:
    def __init__(self, vector_brain: VectorBrain, host: str, port: int):
        self.vector_brain = vector_brain
        self.host = host
        self.port = port
        self.my_url = f"http://{host}:{port}"
        
        # In a real DHT network, we would discover peers dynamically.
        # For simplicity in this demo, we'll hardcode some possible local peer ports
        self.known_peers = set([
            "http://127.0.0.1:8000",
            "http://127.0.0.1:8001",
            "http://127.0.0.1:8002"
        ])
        if self.my_url in self.known_peers:
            self.known_peers.remove(self.my_url)
            
        self.client = httpx.AsyncClient(timeout=5.0)

    async def broadcast_centroids_loop(self):
        """Periodically runs clustering and broadcasts centroids to peers."""
        print("🌐 Starting P2P Gossip Loop...")
        while True:
            # 1. Compute local centroids (e.g. max 20)
            centroids = self.vector_brain.compute_centroids(n_clusters=20)
            if centroids:
                cluster_ids = [f"cluster_{i}" for i in range(len(centroids))]
                
                payload = {
                    "peer_id": self.my_url,
                    "centroids": centroids,
                    "cluster_ids": cluster_ids
                }
                
                # 2. Broadcast to known peers
                for peer in self.known_peers:
                    try:
                        await self.client.post(f"{peer}/p2p/handshake", json=payload)
                        print(f"📡 Sent centroids to {peer}")
                    except Exception as e:
                        pass # Peer might be offline
                        
            await asyncio.sleep(60 * 60) # Run every 1 hour

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
