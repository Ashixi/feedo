import time
import os
from fastapi import Request
from fastapi.responses import JSONResponse
import httpx
from eth_account.messages import encode_defunct
from eth_account import Account
from typing import Optional

# In Feedo, the Consensus Node holds the ledger of registered DIDs
CONSENSUS_NODE_URL = os.getenv("CONSENSUS_NODE_URL", "http://127.0.0.1:3000")


async def _resolve_delegation(address: str) -> Optional[str]:
    """Resolve a delegated usage key (0xD) to its owner wallet address (0xW).

    Returns the owner address (without the 'did:feedo:' prefix) or None.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{CONSENSUS_NODE_URL}/did/{address}/delegation", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                owner = data.get("owner")
                if owner:
                    return owner.split("did:feedo:")[-1]
    except Exception as e:
        print(f"Warning: Failed to resolve delegation for {address}: {e}")
    return None

async def verify_feedo_auth(request: Request):
    """
    Middleware function to verify DID signature and check consensus.
    If valid, returns None. If invalid, returns JSONResponse with 401/400.
    """
    path = request.url.path
    
    # Exclude specific internal endpoints from DID auth
    # Note: p2p routes are node-to-node and should have their own auth (or none, depending on P2P design)
    if path.startswith("/p2p/") or path.startswith("/v1/node/") or path == "/explorer/stats":
        return None
        
    did = request.headers.get("X-Feedo-DID")
    timestamp_str = request.headers.get("X-Feedo-Timestamp")
    signature = request.headers.get("X-Feedo-Signature")
    
    if not did or not timestamp_str or not signature:
        return JSONResponse(status_code=401, content={"detail": "Missing Feedo Authentication Headers. Required: X-Feedo-DID, X-Feedo-Timestamp, X-Feedo-Signature"})
        
    try:
        timestamp_ms = int(timestamp_str)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid timestamp format"})
        
    # 1. Prevent Replay Attacks (5 minutes window)
    current_time_ms = int(time.time() * 1000)
    if abs(current_time_ms - timestamp_ms) > 5 * 60 * 1000:
        return JSONResponse(status_code=401, content={"detail": "Timestamp expired or too far in the future."})
        
    # 2. Reconstruct the signed payload
    # Payload format: FeedoAction:<Method>:<Path>:<Timestamp>
    method = request.method
    payload = f"FeedoAction:{method}:{path}:{timestamp_str}"
    
    # 3. Recover address from signature
    try:
        message = encode_defunct(text=payload)
        recovered_address = Account.recover_message(message, signature=signature)
    except Exception as e:
        return JSONResponse(status_code=401, content={"detail": f"Invalid signature: {str(e)}"})
        
    # 4. Verify recovered address matches the DID
    # Format of DID: did:feedo:0xAddress
    if not did.startswith("did:feedo:"):
        return JSONResponse(status_code=400, content={"detail": "Invalid DID format. Expected did:feedo:0x..."})
        
    did_address = did.split("did:feedo:")[1]
    
    if recovered_address.lower() != did_address.lower():
        # Not a direct signature. It may be a delegated usage key (0xD) acting for this DID (0xW).
        delegated_owner = await _resolve_delegation(recovered_address)
        if delegated_owner is None or delegated_owner.lower() != did_address.lower():
            return JSONResponse(status_code=401, content={"detail": "Signature does not match the provided DID"})
        
    # 5. Consensus Check: verify the DID is registered in the network
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{CONSENSUS_NODE_URL}/did/{did_address}/balance", timeout=5.0)
            if resp.status_code != 200 or resp.json() is None:
                return JSONResponse(status_code=401, content={"detail": "DID not registered in Consensus Node"})
    except Exception as e:
        # In a real distributed system, if consensus is temporarily unreachable, you might want a fallback.
        # But for hard token-gating, we fail closed.
        print(f"Warning: Failed to reach Consensus Node for DID verification: {e}")
        return JSONResponse(status_code=500, content={"detail": "Could not verify DID with Consensus Node"})
        
    # If all checks pass, request is authorized
    return None
