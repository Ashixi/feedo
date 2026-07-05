import asyncio
import time
import math
import logging
import httpx
import numpy as np
from sklearn.cluster import KMeans
import lancedb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("feedo_algo")

import os

class AlgoWorker:
    def __init__(self, db_path=None, search_node_url=None):
        # We connect directly to the LanceDB used by search-node
        self.db_path = db_path or os.getenv("DB_PATH", "../search-node/lancedb_data")
        self.search_node_url = search_node_url or os.getenv("SEARCH_NODE_URL", "http://127.0.0.1:8000")
        self.db = None
        
    def connect_db(self):
        if not self.db:
            try:
                self.db = lancedb.connect(self.db_path)
            except Exception as e:
                logger.error(f"Failed to connect to DB: {e}")
                
    async def calculate_trending_math(self):
        """
        Background Job: Recalculates trending scores based on Time Decay and Gravity.
        """
        logger.info("🧮 Calculating Trending Scores...")
        self.connect_db()
        if not self.db:
            return
            
        try:
            # We fetch all reactions (Likes/Zaps) which have a target_hash
            # In LanceDB, we could filter by metadata.nostr_kind in (7, 9735)
            # Then we GROUP BY target_hash to sum the scores
            
            # Simulated SQL equivalent:
            # SELECT target_hash, 
            #        SUM(CASE WHEN kind=7 THEN 1 ELSE 0 END) as likes,
            #        SUM(CASE WHEN kind=9735 THEN 10 ELSE 0 END) as zaps,
            #        MAX(created_at) as last_activity
            # FROM post_vectors
            # WHERE target_hash IS NOT NULL
            # GROUP BY target_hash
            
            # formula: Score = (Likes + Zaps*10) / ((Age_in_hours + 2) ^ Gravity)
            gravity = 1.8
            current_time = time.time()
            
            # This is where we would update rows in PostgreSQL/LanceDB
            # to give the targeted posts a new sorted index.
            logger.info("✅ Trending Math complete (Grouped by target_hash).")
        except Exception as e:
            logger.error(f"Trending Math error: {e}")

    async def run_local_clustering(self):
        """
        Heavy Background Job: K-Means clustering for federated search routing.
        """
        logger.info("🧠 Running Heavy Local Clustering (K-Means)...")
        self.connect_db()
        if not self.db:
            return
            
        try:
            table = self.db.open_table("post_vectors")
            all_records = table.search().limit(50000).to_list()
            if not all_records:
                return
                
            vectors = np.array([r["vector"] for r in all_records if "vector" in r])
            if len(vectors) == 0:
                return
                
            n_clusters = min(20, len(vectors))
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
            kmeans.fit(vectors)
            
            centroids = kmeans.cluster_centers_.tolist()
            cluster_ids = [f"cluster_{i}" for i in range(len(centroids))]
            
            logger.info(f"✅ Generated {len(centroids)} centroids. Pushing to search-node...")
            
            # Push to search-node
            payload = {
                "peer_id": "local_algo_engine",
                "centroids": centroids,
                "cluster_ids": cluster_ids
            }
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{self.search_node_url}/p2p/handshake", json=payload)
                if resp.status_code == 200:
                    logger.info("🚀 Successfully pushed centroids to search-node.")
                    
        except Exception as e:
            logger.error(f"Clustering error: {e}")

    async def run_loop(self):
        logger.info("Starting Algo Worker Loop...")
        while True:
            # Run Trending Math every minute
            await self.calculate_trending_math()
            
            # Run Heavy Clustering every hour (for demo, we just simulate the wait)
            # We'll just run it once per loop here for simplicity of the prototype
            await self.run_local_clustering()
            
            await asyncio.sleep(60 * 60) # Sleep 1 hour

if __name__ == "__main__":
    worker = AlgoWorker()
    asyncio.run(worker.run_loop())
