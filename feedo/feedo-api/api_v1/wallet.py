from fastapi import APIRouter, HTTPException, Request
import httpx
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/{address}/balance")
async def get_wallet_balance(address: str, request: Request):
    """
    Get the virtual off-chain balance of an address or Feedo ID.
    Proxies the request to the local Rust node's accounting module.
    """
    # RUST_CORE_URL is typically "http://127.0.0.1:8041/local/publish"
    rust_url_base = os.getenv("RUST_CORE_URL", "http://127.0.0.1:8041/local/publish").replace("/local/publish", "")
    
    try:
        rust_balance_url = f"{rust_url_base}/local/balance/{address}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(rust_balance_url, timeout=5.0)
            
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.warning(f"Failed to fetch balance from Rust for {address}: {resp.text}")
            return {"balance": 0.0, "status": "fallback"}
            
    except Exception as e:
        logger.error(f"Error proxying balance request for {address}: {e}")
        return {"balance": 0.0, "status": "error"}
