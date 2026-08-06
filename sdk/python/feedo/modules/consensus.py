import httpx
from typing import Dict, Any, Optional
from ..router import NodeRouter

class ConsensusModule:
    def __init__(self, router: NodeRouter):
        self.router = router

    async def _request(self, method: str, path: str, json: Optional[Dict] = None) -> Any:
        base_url = await self.router.get_consensus_node()
        url = f"{base_url}{path}"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, json=json)
                response.raise_for_status()
                return response.json()
            except Exception:
                print(f"Consensus request failed on {base_url}, finding new node...")
                self.router.invalidate_consensus_node()
                base_url = await self.router.get_consensus_node()
                url = f"{base_url}{path}"
                response = await client.request(method, url, json=json)
                response.raise_for_status()
                return response.json()

    async def resolve_name(self, name: str):
        return await self._request("GET", f"/resolve/{name}")

    async def resolve_cid(self, cid: str):
        return await self._request("GET", f"/resolve_cid/{cid}")

    async def get_did_balance(self, did: str):
        return await self._request("GET", f"/did/{did}/balance")

    async def register_did(self, pubkey_hex: str, signature_hex: str):
        return await self._request("POST", "/did/register", json={"pubkey_hex": pubkey_hex, "signature_hex": signature_hex})

    async def register_name(self, name: str, did: str, cid: str, signature_hex: str):
        return await self._request("POST", "/name/register", json={"name": name, "did": did, "cid": cid, "signature_hex": signature_hex})

    async def update_name_cid(self, name: str, new_cid: str, signature_hex: str):
        return await self._request("POST", "/name/update_cid", json={"name": name, "new_cid": new_cid, "signature_hex": signature_hex})

    async def list_grants(self):
        return await self._request("GET", "/grants")
