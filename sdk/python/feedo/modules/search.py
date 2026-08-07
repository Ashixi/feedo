import httpx
import time
from typing import Dict, Any, Optional
from eth_account.messages import encode_defunct
from eth_account import Account
from ..router import NodeRouter

class SearchModule:
    def __init__(self, router: NodeRouter, private_key: Optional[str] = None):
        self.router = router
        self.private_key = private_key

    async def _request(self, method: str, path: str, json: Optional[Dict] = None, params: Optional[Dict] = None) -> Any:
        base_url = await self.router.get_search_node()
        url = f"{base_url}{path}"
        
        headers = {}
        if self.private_key:
            account = Account.from_key(self.private_key)
            did = f"did:feedo:{account.address}"
            timestamp = str(int(time.time() * 1000))
            # Sign only the base path (without query string) to match server-side auth
            base_path = path.split('?')[0]
            payload_str = f"FeedoAction:{method}:{base_path}:{timestamp}"
            message = encode_defunct(text=payload_str)
            signed_message = Account.sign_message(message, private_key=self.private_key)
            
            headers['X-Feedo-DID'] = did
            headers['X-Feedo-Timestamp'] = timestamp
            headers['X-Feedo-Signature'] = signed_message.signature.hex()

        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, json=json, params=params, headers=headers)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                print(f"Search request failed on {base_url}, finding new node...")
                self.router.invalidate_search_node()
                base_url = await self.router.get_search_node()
                url = f"{base_url}{path}"
                response = await client.request(method, url, json=json, params=params, headers=headers)
                response.raise_for_status()
                return response.json()

    async def search(self, query: str, limit: int = 50, federated: bool = True, item_type: str = "all", offset: int = 0, app_id: Optional[str] = None):
        params = {
            "text": query,
            "limit": limit,
            "federated": "true" if federated else "false",
            "item_type": item_type,
            "offset": offset
        }
        if app_id:
            params["app_id"] = app_id
        return await self._request("GET", "/query", params=params)

    async def query(self, query_text: str, limit: int = 10, item_type: str = "all", app_id: Optional[str] = None):
        """Alias for search() for backwards compatibility."""
        return await self.search(query_text, limit=limit, item_type=item_type, app_id=app_id)

    async def index_private_document(self, hash_id: str, plaintext: str, metadata: dict = None):
        if not self.private_key:
            raise ValueError("Private key required to index private documents")
            
        my_account = Account.from_key(self.private_key)
        my_did = f"did:feedo:{my_account.address}"
        
        payload = {
            "hash_id": hash_id,
            "text": plaintext,
            "item_type": "private_post",
            "author": my_did,
            "metadata": metadata or {}
        }
        return await self._request("POST", "/index_document", json=payload)

    async def index_document(self, content: str, metadata: Optional[Dict] = None):
        import random, string
        metadata = metadata or {}
        hash_id = 'doc_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=7))
        item_type = metadata.get("type", "document")
        return await self._request("POST", "/index_document", json={"text": content, "metadata": metadata, "hash_id": hash_id, "item_type": item_type})

    async def get_documents(self, limit: int = 50, offset: int = 0, item_type: str = "all", app_id: Optional[str] = None):
        params = {"limit": limit, "offset": offset, "item_type": item_type}
        if app_id:
            params["app_id"] = app_id
        return await self._request("GET", "/documents", params=params)

    async def deploy_proxy(self, directory_path: str, domain: str):
        return await self._request("POST", "/proxy/publish_feedo", json={"source_dir": directory_path, "domain": domain})

    async def unpin(self, cid: str):
        return await self._request("DELETE", f"/proxy/unpin_feedo/{cid}")

    async def get_stats(self):
        return await self._request("GET", "/explorer/stats")
