import httpx
from abc import ABC, abstractmethod
import json

class BaseStorageAdapter(ABC):
    """
    Abstract base class for all storage adapters.
    This allows search-node to be completely universal.
    """
    
    @abstractmethod
    async def get_new_hashes(self) -> list[str]:
        """Return a list of new hashes available in the storage."""
        pass
        
    @abstractmethod
    async def download_file(self, hash_id: str) -> bytes | None:
        """Download the raw file data for a given hash."""
        pass


class FeedoStorageAdapter(BaseStorageAdapter):
    def __init__(self, storage_url=None):
        import os
        self.storage_url = storage_url or os.getenv("STORAGE_NODE_URL", "http://127.0.0.1:3001")
        self.client = httpx.AsyncClient(timeout=10.0)
        
    async def get_new_hashes(self) -> list[str]:
        # We assume the Rust node will expose a way to get recent hashes
        # E.g. GET /api/files/recent
        try:
            resp = await self.client.get(f"{self.storage_url}/api/files/recent")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("hashes", [])
        except httpx.ConnectError:
            pass # Suppress connection spam if node is booting
        except Exception as e:
            if "404" not in str(e): # Suppress 404 since endpoint might not exist yet
                print(f"⚠️ FeedoStorageAdapter error fetching hashes: {e}")
        return []
        
    async def download_file(self, hash_id: str) -> bytes | None:
        try:
            resp = await self.client.get(f"{self.storage_url}/download/{hash_id}")
            if resp.status_code == 200:
                return resp.content
        except Exception as e:
            print(f"⚠️ FeedoStorageAdapter error downloading {hash_id}: {e}")
        return None


class IPFSStorageAdapter(BaseStorageAdapter):
    def __init__(self, gateway_url="https://ipfs.io/ipfs/"):
        self.gateway_url = gateway_url
        self.client = httpx.AsyncClient(timeout=15.0)
        
    async def get_new_hashes(self) -> list[str]:
        # IPFS doesn't naturally have a 'recent files' global feed without a custom indexer
        # For now, this is a stub for IPFS compatibility
        return []
        
    async def download_file(self, hash_id: str) -> bytes | None:
        try:
            resp = await self.client.get(f"{self.gateway_url}{hash_id}")
            if resp.status_code == 200:
                return resp.content
        except Exception as e:
            print(f"⚠️ IPFSStorageAdapter error downloading {hash_id}: {e}")
        return None
