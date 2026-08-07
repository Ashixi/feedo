import asyncio
import httpx
import os
import logging
from typing import List, Set

logger = logging.getLogger(__name__)

class PeerDiscovery:
    def __init__(self, bootstrap_storage: List[str], bootstrap_consensus: List[str]):
        """
        Initialize with lists of known nodes.
        Filters out empty strings.
        """
        self.known_storage_nodes: Set[str] = set([url for url in bootstrap_storage if url])
        self.known_consensus_nodes: Set[str] = set([url for url in bootstrap_consensus if url])
        self.known_consensus_grpc: Set[str] = set()
        self.refresh_interval = 3600  # 1 hour

    async def _refresh_nodes(self, known_set: Set[str], peer_key: str, grpc_set: Set[str] = None, grpc_key: str = None):
        if not known_set:
            return

        new_nodes = set()
        new_grpc = set()
        async with httpx.AsyncClient(timeout=5.0) as client:
            for url in list(known_set):
                try:
                    resp = await client.get(f"{url}/api/v1/peers")
                    if resp.status_code == 200:
                        data = resp.json()
                        peers = data.get(peer_key, [])
                        new_nodes.update(peers)
                        
                        if grpc_set is None:
                            continue
                            
                        if grpc_key and grpc_key in data:
                            new_grpc.update(data[grpc_key])
                            
                except Exception as e:
                    logger.debug(f"Failed to fetch peers from {url}: {e}")

        before_count = len(known_set)
        known_set.update(new_nodes)
        
        if grpc_set is not None:
            grpc_set.update(new_grpc)
        after_count = len(known_set)
        if after_count > before_count:
            logger.info(f"Discovered {after_count - before_count} new {peer_key}. Total: {after_count}")

    async def refresh(self):
        """Polls all known nodes for their peers and expands the sets."""
        await asyncio.gather(
            self._refresh_nodes(self.known_storage_nodes, "storage_nodes"),
            self._refresh_nodes(self.known_consensus_nodes, "consensus_nodes", self.known_consensus_grpc, "consensus_grpc")
        )

    async def run_forever(self):
        """Background loop to periodically discover new nodes."""
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

    def get_all_consensus_grpc(self) -> List[str]:
        return list(self.known_consensus_grpc)

# Global instance for the Search Node
_discovery_instance = None

def init_discovery(bootstrap_storage: List[str], bootstrap_consensus: List[str]):
    global _discovery_instance
    _discovery_instance = PeerDiscovery(bootstrap_storage, bootstrap_consensus)
    asyncio.create_task(_discovery_instance.run_forever())

def get_storage_nodes() -> List[str]:
    if _discovery_instance:
        return _discovery_instance.get_all_storage_nodes()
    return []

def get_consensus_nodes() -> List[str]:
    if _discovery_instance:
        return _discovery_instance.get_all_consensus_nodes()
    return []

def get_consensus_grpc() -> List[str]:
    if _discovery_instance:
        return _discovery_instance.get_all_consensus_grpc()
    return []
