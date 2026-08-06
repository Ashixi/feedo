import httpx
import asyncio
from typing import List, Optional, Dict

DEFAULT_SEEDS = {
    "search": ["http://95.111.245.68:8000", "http://178.18.253.94:8000", "http://localhost:8000"],
    "consensus": ["http://95.111.245.68:8080", "http://178.18.253.94:8080", "http://localhost:8080"],
    "storage": ["http://95.111.245.68:8081", "http://178.18.253.94:8081", "http://localhost:8081"]
}

class NodeRouter:
    def __init__(self, search_seeds: Optional[List[str]] = None, consensus_seeds: Optional[List[str]] = None, storage_seeds: Optional[List[str]] = None):
        self.search_nodes = search_seeds or DEFAULT_SEEDS["search"]
        self.consensus_nodes = consensus_seeds or DEFAULT_SEEDS["consensus"]
        self.storage_nodes = storage_seeds or DEFAULT_SEEDS["storage"]

        self._active_search_node = None
        self._active_consensus_node = None
        self._active_storage_node = None

    async def _find_fastest_node(self, nodes: List[str], health_endpoint: str) -> str:
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
                    return task.result()
                except Exception:
                    pass
            tasks = list(pending)
            
        print(f"Warning: All seed nodes failed. Falling back to {nodes[0]}")
        return nodes[0]

    async def get_search_node(self) -> str:
        if not self._active_search_node:
            self._active_search_node = await self._find_fastest_node(self.search_nodes, "/explorer/stats")
        return self._active_search_node

    async def get_consensus_node(self) -> str:
        if not self._active_consensus_node:
            self._active_consensus_node = await self._find_fastest_node(self.consensus_nodes, "/grants")
        return self._active_consensus_node

    async def get_storage_node(self) -> str:
        if not self._active_storage_node:
            self._active_storage_node = await self._find_fastest_node(self.storage_nodes, "/api/files/recent")
        return self._active_storage_node

    def invalidate_search_node(self):
        self._active_search_node = None

    def invalidate_consensus_node(self):
        self._active_consensus_node = None

    def invalidate_storage_node(self):
        self._active_storage_node = None
