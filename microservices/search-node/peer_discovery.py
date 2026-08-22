import asyncio
import httpx
import os
import logging
from typing import List, Set

logger = logging.getLogger(__name__)

class PeerDiscovery:
    def __init__(self):
        self.known_storage_nodes: Set[str] = set()
        self.known_consensus_nodes: Set[str] = set()
        self.refresh_interval = 60  # 1 minute
        self.router_url = os.getenv("ROUTER_NODE_URL", "https://router.feedo.ink")

    async def _fetch_from_router(self, node_type: str) -> Set[str]:
        nodes = set()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.router_url}/discover?type={node_type}")
                if resp.status_code == 200:
                    data = resp.json()
                    for node in data.get("nodes", []):
                        url = node.get("internal_http")
                        if url:
                            nodes.add(url)
        except Exception as e:
            logger.debug(f"Failed to fetch {node_type} peers from router: {e}")
        return nodes

    async def refresh(self):
        storage_nodes = await self._fetch_from_router("storage")
        if storage_nodes:
            self.known_storage_nodes = storage_nodes
            
        consensus_nodes = await self._fetch_from_router("consensus")
        if consensus_nodes:
            self.known_consensus_nodes = consensus_nodes

    async def run_forever(self):
        while True:
            try:
                await self.refresh()
            except Exception as e:
                logger.error(f"Error in peer discovery loop: {e}")
            await asyncio.sleep(self.refresh_interval)

    def get_all_storage_nodes(self) -> List[str]:
        return list(self.known_storage_nodes)
        
    def get_all_consensus_nodes(self) -> List[str]:
        return list(self.known_consensus_nodes)

# Global instance for the Search Node
_discovery_instance = None

def init_discovery():
    global _discovery_instance
    _discovery_instance = PeerDiscovery()
    # Trigger an immediate fetch so we have nodes before the loop sleeps
    asyncio.create_task(_discovery_instance.refresh())
    asyncio.create_task(_discovery_instance.run_forever())

def get_storage_nodes() -> List[str]:
    if _discovery_instance:
        return _discovery_instance.get_all_storage_nodes()
    return []

def get_consensus_nodes() -> List[str]:
    if _discovery_instance:
        return _discovery_instance.get_all_consensus_nodes()
    return []
