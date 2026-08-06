import asyncio
import httpx
import os
import logging
from typing import List, Set

logger = logging.getLogger(__name__)

class StoragePeerDiscovery:
    def __init__(self, bootstrap_urls: List[str]):
        """
        Initialize with a list of known storage nodes.
        Filters out empty strings.
        """
        self.known_nodes: Set[str] = set([url for url in bootstrap_urls if url])
        self.refresh_interval = 3600  # 1 hour

    async def refresh(self):
        """Polls all known nodes for their peers and expands the set."""
        if not self.known_nodes:
            logger.warning("No known storage nodes to discover from.")
            return

        new_nodes = set()
        # Use a short timeout so we don't hang if a node is offline
        async with httpx.AsyncClient(timeout=5.0) as client:
            for url in list(self.known_nodes):
                try:
                    resp = await client.get(f"{url}/api/v1/peers")
                    if resp.status_code == 200:
                        data = resp.json()
                        peers = data.get("storage_nodes", [])
                        new_nodes.update(peers)
                except Exception as e:
                    logger.debug(f"Failed to fetch peers from {url}: {e}")

        before_count = len(self.known_nodes)
        self.known_nodes.update(new_nodes)
        after_count = len(self.known_nodes)
        if after_count > before_count:
            logger.info(f"Discovered {after_count - before_count} new storage nodes. Total: {after_count}")

    async def run_forever(self):
        """Background loop to periodically discover new nodes."""
        while True:
            try:
                await self.refresh()
            except Exception as e:
                logger.error(f"Error in peer discovery loop: {e}")
            await asyncio.sleep(self.refresh_interval)

    def get_all_nodes(self) -> List[str]:
        """Returns the list of all currently known storage node URLs."""
        return list(self.known_nodes)

# Global instance for the Search Node
_discovery_instance = None

def init_discovery(bootstrap_urls: List[str]):
    global _discovery_instance
    _discovery_instance = StoragePeerDiscovery(bootstrap_urls)
    asyncio.create_task(_discovery_instance.run_forever())

def get_storage_nodes() -> List[str]:
    """Get the current list of storage node URLs."""
    if _discovery_instance:
        return _discovery_instance.get_all_nodes()
    return []
