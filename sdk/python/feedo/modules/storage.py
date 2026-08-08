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

    async def _upload_single_chunk(self, data: bytes, filename: str) -> str:
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

    async def upload_bytes(self, data: bytes, filename: str = "file") -> str:
        """Upload raw bytes directly. Automatically chunks files > 5MB. Returns the hash ID."""
        CHUNK_SIZE = 5 * 1024 * 1024
        size = len(data)
        if size <= CHUNK_SIZE:
            return await self._upload_single_chunk(data, filename)

        import asyncio
        import json

        chunks = []
        offset = 0
        while offset < size:
            chunks.append(data[offset:offset + CHUNK_SIZE])
            offset += CHUNK_SIZE

        hashes = [None] * len(chunks)
        semaphore = asyncio.Semaphore(10)

        async def upload_worker(idx, chunk):
            async with semaphore:
                chunk_hash = await self._upload_single_chunk(chunk, f"{filename}.part{idx}")
                hashes[idx] = chunk_hash

        tasks = [upload_worker(i, c) for i, c in enumerate(chunks)]
        await asyncio.gather(*tasks)

        manifest = {
            "type": "feedo_manifest",
            "filename": filename,
            "total_size": size,
            "chunk_size": CHUNK_SIZE,
            "chunks": hashes
        }

        manifest_bytes = json.dumps(manifest).encode('utf-8')
        return await self._upload_single_chunk(manifest_bytes, "manifest.json")

    async def _download_single_chunk(self, hash_id: str) -> bytes:
        return await self._request("GET", f"/download/{hash_id}")

    async def download_file(self, hash_id: str) -> bytes:
        """Download a file by its hash ID. Automatically rebuilds chunked files. Returns raw bytes."""
        raw_data = await self._download_single_chunk(hash_id)

        if len(raw_data) < 1024 * 1024:
            import json
            import asyncio
            try:
                text = raw_data.decode('utf-8')
                manifest = json.loads(text)
                if manifest.get("type") == "feedo_manifest" and isinstance(manifest.get("chunks"), list):
                    semaphore = asyncio.Semaphore(10)
                    chunks_data = [None] * len(manifest["chunks"])

                    async def download_worker(idx, h):
                        async with semaphore:
                            chunks_data[idx] = await self._download_single_chunk(h)

                    tasks = [download_worker(i, h) for i, h in enumerate(manifest["chunks"])]
                    await asyncio.gather(*tasks)

                    return b''.join(chunks_data)
            except Exception:
                pass

        return raw_data

    async def ingest_json(self, payload: Dict):
        return await self._request("POST", "/api/v1/ingest/post", json=payload)

    async def get_recent_files(self):
        return await self._request("GET", "/api/files/recent")
