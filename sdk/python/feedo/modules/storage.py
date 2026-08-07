import httpx
import io
import time
from typing import Dict, Any, Optional
from eth_account.messages import encode_defunct
from eth_account import Account
from ..router import NodeRouter

class StorageModule:
    def __init__(self, router: NodeRouter, private_key: Optional[str] = None):
        self.router = router
        self.private_key = private_key

    def _build_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        if not self.private_key:
            return {}
        account = Account.from_key(self.private_key)
        did = f"did:feedo:{account.address}"
        timestamp = str(int(time.time() * 1000))
        payload_str = f"FeedoAction:{method}:{path}:{timestamp}"
        message = encode_defunct(text=payload_str)
        signed_message = Account.sign_message(message, private_key=self.private_key)
        return {
            'X-Feedo-DID': did,
            'X-Feedo-Timestamp': timestamp,
            'X-Feedo-Signature': signed_message.signature.hex()
        }

    async def _request(self, method: str, path: str, json: Optional[Dict] = None, data: Any = None, files: Any = None) -> Any:
        base_url = await self.router.get_storage_node()
        url = f"{base_url}{path}"
        headers = self._build_auth_headers(method, path)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, json=json, data=data, files=files, headers=headers)
                response.raise_for_status()
                if "application/json" in response.headers.get("content-type", ""):
                    return response.json()
                return response.content
            except Exception:
                print(f"Storage request failed on {base_url}, finding new node...")
                self.router.invalidate_storage_node()
                base_url = await self.router.get_storage_node()
                url = f"{base_url}{path}"
                headers = self._build_auth_headers(method, path)
                response = await client.request(method, url, json=json, data=data, files=files, headers=headers)
                response.raise_for_status()
                if "application/json" in response.headers.get("content-type", ""):
                    return response.json()
                return response.content

    async def upload_file(self, file_path: str, filename: str = "file") -> str:
        """Upload a file from a local path. Returns the hash ID."""
        with open(file_path, "rb") as f:
            return await self.upload_bytes(f.read(), filename)

    async def upload_bytes(self, data: bytes, filename: str = "file") -> str:
        """Upload raw bytes directly. Returns the hash ID."""
        base_url = await self.router.get_storage_node()
        url = f"{base_url}/upload"
        headers = self._build_auth_headers("POST", "/upload")

        async with httpx.AsyncClient() as client:
            files = {"file": (filename, io.BytesIO(data), "application/octet-stream")}
            try:
                response = await client.post(url, files=files, headers=headers)
                response.raise_for_status()
                return response.text.strip()
            except Exception:
                print(f"Storage request failed on {base_url}, finding new node...")
                self.router.invalidate_storage_node()
                base_url = await self.router.get_storage_node()
                url = f"{base_url}/upload"
                headers = self._build_auth_headers("POST", "/upload")
                response = await client.post(url, files=files, headers=headers)
                response.raise_for_status()
                return response.text.strip()

    async def download_file(self, hash_id: str) -> bytes:
        """Download a file by its hash ID. Returns raw bytes."""
        return await self._request("GET", f"/download/{hash_id}")

    async def ingest_json(self, payload: Dict):
        return await self._request("POST", "/api/v1/ingest/post", json=payload)

    async def get_recent_files(self):
        return await self._request("GET", "/api/files/recent")
