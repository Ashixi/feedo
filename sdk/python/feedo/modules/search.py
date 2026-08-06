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
            payload_str = f"FeedoAction:{method}:{path}:{timestamp}"
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

    async def query(self, query_text: str, limit: int = 10, item_type: str = "all"):
        return await self._request("GET", "/query", params={"text": query_text, "limit": limit, "item_type": item_type})

    async def index_document(self, content: str, metadata: Optional[Dict] = None):
        import random, string
        metadata = metadata or {}
        hash_id = 'doc_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=7))
        item_type = metadata.get("type", "document")
        return await self._request("POST", "/index_document", json={"text": content, "metadata": metadata, "hash_id": hash_id, "item_type": item_type})

    async def deploy_proxy(self, directory_path: str, domain: str):
        return await self._request("POST", "/proxy/publish_feedo", json={"source_dir": directory_path, "domain": domain})

    async def unpin(self, cid: str):
        return await self._request("DELETE", f"/proxy/unpin_feedo/{cid}")

    async def get_stats(self):
        return await self._request("GET", "/explorer/stats")
