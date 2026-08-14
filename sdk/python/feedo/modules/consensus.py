import httpx
from typing import Dict, Any, Optional
from ..router import NodeRouter
import time
from eth_account.messages import encode_defunct
from eth_account import Account

class ConsensusModule:
    def __init__(self, router: NodeRouter, private_key: Optional[str] = None):
        self.router = router
        self.private_key = private_key

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

    async def register_did(self, private_key_hex: str):
        """
        Register a DID on the Feedo Consensus Network.
        Derives the Ethereum address from the private key, builds did:feedo:0xAddress,
        signs the canonical registration message to prove ownership, and registers it.
        """
        account = Account.from_key(private_key_hex)
        did = f"did:feedo:{account.address}"
        message = f"feedo register {did}"
        signed = account.sign_message(encode_defunct(text=message))
        return await self._request("POST", "/did/register", json={
            "did": did,
            "public_key": account.address,
            "signature": signed.signature.hex(),
        })

    async def register_name(self, name: str, did: str, cid: str, signature_hex: str):
        return await self._request("POST", "/name/register", json={"name": name, "did": did, "cid": cid, "signature_hex": signature_hex})

    async def update_name_cid(self, name: str, new_cid: str, signature_hex: str):
        return await self._request("POST", "/name/update_cid", json={"name": name, "new_cid": new_cid, "signature_hex": signature_hex})

    async def list_grants(self):
        return await self._request("GET", "/grants")

    async def grant_file_access(self, file_hash: str, grantee_did: str, encrypted_symmetric_key: str, public_key: str, signature_hex: str):
        payload = {
            "file_hash": file_hash,
            "grantee_did": grantee_did,
            "encrypted_symmetric_key": encrypted_symmetric_key,
            "public_key": public_key,
            "signature": signature_hex
        }
        return await self._request("POST", "/grant/access", json=payload)

    async def get_file_access(self, file_hash: str, grantee_did: str):
        return await self._request("GET", f"/grant/access/{file_hash}/{grantee_did}")
