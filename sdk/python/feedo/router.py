import httpx
import asyncio
from typing import List, Optional, Dict

import time

ROUTER_URL = "https://router.feedo.ink"

class NodeRouter:
    def __init__(self, router_url: Optional[str] = None):
        self.router_url = router_url or ROUTER_URL
        
        self._active_search_node = None
        self._active_consensus_node = None
        self._active_storage_node = None
        
        # Cache discovered nodes to avoid spamming the router
        self._cache = {"search": ([], 0), "consensus": ([], 0), "storage": ([], 0)}
        self._cache_ttl = 300 # 5 minutes

    async def _get_nodes_from_router(self, node_type: str) -> List[str]:
        cached_nodes, cache_time = self._cache[node_type]
        if time.time() - cache_time < self._cache_ttl and cached_nodes:
            return cached_nodes
            
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.router_url}/discover?type={node_type}", timeout=5.0)
                resp.raise_for_status()
                data = resp.json()
                nodes = []
                for node in data.get("nodes", []):
                    # Prefer public_domain for external SDKs, fallback to internal_http
                    url = node.get("public_domain") or node.get("internal_http")
                    if url:
                        nodes.append(url)
                
                if nodes:
                    self._cache[node_type] = (nodes, time.time())
                    return nodes
        except Exception as e:
            print(f"Warning: Failed to fetch {node_type} nodes from router {self.router_url}: {e}")
            
        return cached_nodes

    async def _find_fastest_node(self, node_type: str, health_endpoint: str) -> str:
        nodes = await self._get_nodes_from_router(node_type)
        if not nodes:
            # Fallbacks if router is completely down
            fallbacks = {
                "search": ["https://api.feedo.ink", "http://localhost:8000"],
                "consensus": ["https://api.feedo.ink/consensus", "http://localhost:3000"],
                "storage": ["https://api.feedo.ink/storage", "http://localhost:3001"]
            }
            nodes = fallbacks.get(node_type, [])

        async def ping(node: str) -> str:
            async with httpx.AsyncClient() as client:
                url = f"{node}{health_endpoint}"
                response = await client.get(url, timeout=3.0)
                response.raise_for_status()
                return node

        tasks = [asyncio.create_task(ping(node)) for node in nodes]
        
        while tasks:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    result = task.result()
                    for p in pending:
                        p.cancel()
                    return result
                except Exception:
                    pass
            tasks = list(pending)
            
        print(f"Warning: All discovered {node_type} nodes failed. Falling back to {nodes[0] if nodes else 'unknown'}")
        return nodes[0] if nodes else ""

    async def get_search_node(self) -> str:
        if not self._active_search_node:
            self._active_search_node = await self._find_fastest_node("search", "/explorer/stats")
        return self._active_search_node

    async def get_consensus_node(self) -> str:
        if not self._active_consensus_node:
            self._active_consensus_node = await self._find_fastest_node("consensus", "/grants")
        return self._active_consensus_node

    async def get_storage_node(self) -> str:
        if not self._active_storage_node:
            self._active_storage_node = await self._find_fastest_node("storage", "/api/files/recent")
        return self._active_storage_node

    def invalidate_search_node(self):
        self._active_search_node = None

    def invalidate_consensus_node(self):
        self._active_consensus_node = None

    def invalidate_storage_node(self):
        self._active_storage_node = None
