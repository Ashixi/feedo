import asyncio
import httpx
import logging
import time
from typing import List, Dict, Set, Optional
from collections import defaultdict

logger = logging.getLogger("feedo_aggregator")

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = defaultdict(int)
        self.last_failure_time = defaultdict(float)
        
    def record_failure(self, peer: str):
        self.failures[peer] += 1
        self.last_failure_time[peer] = time.time()
        
    def record_success(self, peer: str):
        if peer in self.failures:
            del self.failures[peer]
            del self.last_failure_time[peer]
            
    def is_open(self, peer: str) -> bool:
        if self.failures[peer] >= self.failure_threshold:
            if time.time() - self.last_failure_time[peer] > self.recovery_timeout:
                # Half-open state
                return False
            return True
        return False

class AggregatorClient:
    def __init__(self, api_key: str = "", timeout: float = 5.0):
        self.api_key = api_key
        self.timeout = timeout
        self.circuit_breaker = CircuitBreaker()
        
    def _get_headers(self):
        return {"x-vector-api-key": self.api_key} if self.api_key else {}
        
    async def fetch_recent_hash_ids(self, peer_addr: str, limit: int = 50, since: float = 0.0) -> List[str]:
        if self.circuit_breaker.is_open(peer_addr):
            return []
            
        async with httpx.AsyncClient() as client:
            try:
                res = await client.get(
                    f"{peer_addr}/internal/vector/recent?limit={limit}&since={since}", 
                    headers=self._get_headers(), 
                    timeout=self.timeout
                )
                if res.status_code == 200:
                    self.circuit_breaker.record_success(peer_addr)
                    return res.json().get("recent_hash_ids", [])
                else:
                    self.circuit_breaker.record_failure(peer_addr)
            except Exception as e:
                self.circuit_breaker.record_failure(peer_addr)
                logger.debug(f"Failed to fetch recent from {peer_addr}: {e}")
        return []
        
    async def fetch_vector(self, peer_addr: str, hash_id: str) -> Dict:
        if self.circuit_breaker.is_open(peer_addr):
            return {}
            
        async with httpx.AsyncClient() as client:
            try:
                res = await client.get(
                    f"{peer_addr}/internal/vector/by_post/{hash_id}", 
                    headers=self._get_headers(), 
                    timeout=self.timeout
                )
                if res.status_code == 200:
                    self.circuit_breaker.record_success(peer_addr)
                    return res.json()
                else:
                    self.circuit_breaker.record_failure(peer_addr)
            except Exception as e:
                self.circuit_breaker.record_failure(peer_addr)
                logger.debug(f"Failed to fetch vector {hash_id} from {peer_addr}: {e}")
        return {}

    async def batch_fetch_vectors(self, peer_addr: str, hash_ids: List[str]) -> List[Dict]:
        tasks = [self.fetch_vector(peer_addr, hid) for hid in hash_ids]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r]
        
    async def deduplicated_query(self, peers: List[str], vectors: List[List[float]], k: int = 50) -> List[List[Dict]]:
        """Parallel query to multiple peers, merge and deduplicate by hash_id taking best score for each vector in the batch."""
        async def query_peer(peer):
            if self.circuit_breaker.is_open(peer):
                return []
            async with httpx.AsyncClient() as client:
                try:
                    res = await client.post(
                        f"{peer}/internal/vector/batch_query",
                        json={"vectors": vectors, "k": k},
                        headers=self._get_headers(),
                        timeout=self.timeout
                    )
                    if res.status_code == 200:
                        self.circuit_breaker.record_success(peer)
                        return res.json()
                    else:
                        self.circuit_breaker.record_failure(peer)
                except Exception as e:
                    self.circuit_breaker.record_failure(peer)
            return []

        peer_results = await asyncio.gather(*[query_peer(p) for p in peers])
        
        final_results = []
        for i in range(len(vectors)):
            merged = defaultdict(float)
            for p_res in peer_results:
                if p_res and isinstance(p_res, list) and len(p_res) > i:
                    res_for_vec = p_res[i]
                    if isinstance(res_for_vec, list):
                        for item in res_for_vec:
                            if "hash_id" in item and "score" in item:
                                hid = item["hash_id"]
                                score = item["score"]
                                if score > merged[hid]:
                                    merged[hid] = score
                                    
            sorted_results = [{"hash_id": hid, "score": score} for hid, score in sorted(merged.items(), key=lambda x: x[1], reverse=True)]
            final_results.append(sorted_results[:k])
            
        return final_results
