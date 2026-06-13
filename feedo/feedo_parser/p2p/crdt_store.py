import time
import httpx
from typing import Optional, Dict

class FeedoMap:

    def __init__(self, object_id: str, author_did: str, api_url: str = "http://127.0.0.1:8040"):
        self.object_id = object_id
        self.author_did = author_did
        self.api_url = api_url

    async def get_state(self) -> Dict:
        """
        Fetch the current converged state from the local node.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.api_url}/api/v1/crdt/{self.object_id}")
            if resp.status_code == 200:
                data = resp.json()
                if "entries" in data:
                    # Flatten the entries into a simple map for the developer
                    return {k: v["value"] for k, v in data["entries"].items() if not v.get("is_deleted", False)}
                return data
            return {}

    async def set(self, key: str, value: str, signature: str) -> bool:

        timestamp = int(time.time())
        payload = {
            "object_id": self.object_id,
            "crdt_type": "LWWMap",
            "operation": "set",
            "key": key,
            "value": value,
            "author": self.author_did,
            "signature": signature
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.api_url}/api/v1/crdt/mutate", json=payload)
            return resp.status_code == 200

    async def delete(self, key: str, signature: str) -> bool:

        timestamp = int(time.time())
        payload = {
            "object_id": self.object_id,
            "crdt_type": "LWWMap",
            "operation": "delete",
            "key": key,
            "value": "",
            "author": self.author_did,
            "signature": signature
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.api_url}/api/v1/crdt/mutate", json=payload)
            return resp.status_code == 200

class FeedoAwOrSet:

    def __init__(self, object_id: str, author_did: str, api_url: str = "http://127.0.0.1:8040"):
        self.object_id = object_id
        self.author_did = author_did
        self.api_url = api_url

    async def get_state(self) -> list:
 
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.api_url}/api/v1/crdt/{self.object_id}")
            if resp.status_code == 200:
                data = resp.json()
                if "elements" in data:
                    return list(data["elements"].keys())
                return data
            return []

    async def add(self, value: str, signature: str) -> str:

        import uuid
        vector_tag = str(uuid.uuid4())
        
        payload = {
            "object_id": self.object_id,
            "crdt_type": "AwOrSet",
            "operation": "add",
            "key": value, 
            "value": value,
            "author": self.author_did,
            "signature": signature,
            "vector_tag": vector_tag,
            "remove_tags": []
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.api_url}/api/v1/crdt/mutate", json=payload)
            if resp.status_code == 200:
                return vector_tag
            return None

    async def remove(self, value: str, remove_tags: list[str], signature: str) -> bool:
        """
        Remove an element from the set by specifying the tags observed.
        """
        payload = {
            "object_id": self.object_id,
            "crdt_type": "AwOrSet",
            "operation": "remove",
            "key": value,
            "value": value,
            "author": self.author_did,
            "signature": signature,
            "vector_tag": None,
            "remove_tags": remove_tags
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.api_url}/api/v1/crdt/mutate", json=payload)
            return resp.status_code == 200
