import httpx
import time
from typing import Dict, Any, Optional
from eth_account.messages import encode_defunct
from eth_account import Account
from ..router import NodeRouter

class StorageModule:
    def __init__(self, router: NodeRouter, private_key: Optional[str] = None):
        self.router = router
        self.private_key = private_key

    async def _request(self, method: str, path: str, json: Optional[Dict] = None, data: Any = None, files: Any = None) -> Any:
        base_url = await self.router.get_storage_node()
        url = f"{base_url}{path}"
        
        headers = {}
        if self.private_key:
            account = Account.from_key(self.private_key)
            did = f"did:feedo:{account.address}"
            timestamp = str(int(time.time() * 1000))
            payload_str = f"FeedoAction:{method}:{path}:{timestamp}"
            message = encode_defunct(text=payload_str)
            signed_message = Account.sign_message(message, private_key=self.private_key)
            
            headers['X-Feedo-DID'] = did
            headers['X-Feedo-Timestamp'] = timestamp
            headers['X-Feedo-Signature'] = signed_message.signature.hex()

        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, json=json, data=data, files=files, headers=headers)
                response.raise_for_status()
                # download endpoint might not return json
                if response.headers.get("content-type") == "application/json":
                    return response.json()
                return response.content
            except Exception:
                print(f"Storage request failed on {base_url}, finding new node...")
                self.router.invalidate_storage_node()
                base_url = await self.router.get_storage_node()
                url = f"{base_url}{path}"
                response = await client.request(method, url, json=json, data=data, files=files, headers=headers)
                response.raise_for_status()
                if response.headers.get("content-type") == "application/json":
                    return response.json()
                return response.content

    async def upload_file(self, file_path: str, filename: str = "file"):
        with open(file_path, "rb") as f:
            files = {"file": (filename, f)}
            return await self._request("POST", "/upload", files=files)

    async def download_file(self, hash_id: str) -> bytes:
        return await self._request("GET", f"/download/{hash_id}")

    async def ingest_json(self, payload: Dict):
        return await self._request("POST", "/api/v1/ingest/post", json=payload)

    async def get_recent_files(self):
        return await self._request("GET", "/api/files/recent")
