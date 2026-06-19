from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Any, Optional
import httpx
import os
import time

from database import get_db
from models import Post
from pydantic import BaseModel

router = APIRouter()

RUST_CORE_URL = os.getenv("RUST_CORE_URL", "http://127.0.0.1:8041/local/publish")

class PublishRequest(BaseModel):
    text: str
    author: str
    signature: str
    hash_id: str
    content_blob_hash: str
    title: Optional[str] = None
    source_type: Optional[str] = "native"
    sequence_number: int = 1
    timestamp: int
    metadata_: Optional[Dict[str, Any]] = None

@router.post("/publish")
async def publish_content(req: PublishRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Publish content to mempool for AI-validation and PBFT consensus."""
    
    # 1. Zero-Trust validation
    from feedo_parser.crypto_utils import verify_signature
    import time
    
    # Check timestamp against Replay Attacks
    now = int(time.time())
    if abs(now - req.timestamp) > 300:
        raise HTTPException(status_code=401, detail="Timestamp is invalid or expired (Replay Attack protection).")
        
    # The SDK hashes (text_content + "_" + timestamp)
    # The signature must match this hash_id
    if not verify_signature(req.hash_id, req.signature, req.author):
        raise HTTPException(status_code=401, detail="Zero Trust Auth Failed: Invalid signature for hash_id!")

    # Proxy to Rust core for PBFT
    async with httpx.AsyncClient() as client:
        try:
            import feedo_pb2
            pb_req = feedo_pb2.PublishRequest()
            pb_req.text = req.text
            pb_req.author = req.author
            pb_req.signature = req.signature
            pb_req.hash_id = req.hash_id
            pb_req.content_blob_hash = req.content_blob_hash
            if req.title:
                pb_req.title = req.title
            if req.source_type:
                pb_req.source_type = req.source_type
            pb_req.sequence_number = req.sequence_number
            if req.metadata_:
                import json
                pb_req.metadata = json.dumps(req.metadata_)
            
            payload_bytes = pb_req.SerializeToString()
            
            res = await client.post(RUST_CORE_URL, content=payload_bytes, headers={"Content-Type": "application/octet-stream"}, timeout=10.0)
            if res.status_code != 200:
                raise HTTPException(status_code=res.status_code, detail=res.text)
            
            return {"status": "ok", "message": res.text}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to contact rust core: {str(e)}")

@router.get("/{hash_id}")
async def get_content(hash_id: str, request: Request, client_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Get a specific note/article. Fetch via Kademlia DHT or Proxy if missing locally."""
    from tokenomics_service import TokenomicsService
    import httpx
    import websockets
    import asyncio
    import json
    
    if not client_id:
        raise HTTPException(status_code=402, detail="Payment required: client_id must be provided for proxy fetching.")
        
    cost = 1
    is_free = False
    success = await TokenomicsService.pay_for_query(db, client_id, cost=cost, allow_free_quota=True)
    if not success:
        if not TokenomicsService.check_free_tier_rate_limit(client_id):
            raise HTTPException(status_code=429, detail="Free tier rate limit exceeded (5 req/min). Please top up funds for proxy fetching.")
        is_free = True

    stmt = select(Post).where(Post.hash_id == hash_id)
    post = (await db.execute(stmt)).scalar_one_or_none()
    
    if not post:
        raise HTTPException(status_code=404, detail="Content not found locally or in DHT")
        
    # If text is present, return it directly
    if post.text_content:
        # Give author a cut since we hit their content
        if not is_free:
            await TokenomicsService.reward_query_hit(db, post.author_address, None, fee_amount=cost)
        return {
            "hash_id": post.hash_id,
            "text": post.text_content,
            "author": post.author_address,
            "metadata": post.metadata_,
            "status": "finalized" if post.is_finalized else "mempool",
            "source": "local_db"
        }
        
    # Proxy Fetching Logic
    fetched_text = None
    source = "proxy"
    
    if post.source_type == "paragraph" and post.metadata_:
        tx_id = post.metadata_.get("tx_id")
        if tx_id:
            try:
                async with httpx.AsyncClient() as client:
                    res = await client.get(f"https://arweave.net/{tx_id}", timeout=5.0)
                    if res.status_code == 200:
                        data = res.json()
                        fetched_text = data.get("content", {}).get("body") or data.get("text", "")
                        source = "proxy_arweave"
            except Exception as e:
                logger.error(f"Arweave fetch failed for {tx_id}: {e}")
                
    elif post.source_type == "nostr" and post.relay_url:
        try:
            # Connect to Nostr relay and send REQ
            async with websockets.connect(post.relay_url, open_timeout=3.0) as ws:
                req_msg = ["REQ", "feedo_fetch", {"ids": [hash_id]}]
                await ws.send(json.dumps(req_msg))
                
                # Wait for response with timeout
                start_time = asyncio.get_event_loop().time()
                while asyncio.get_event_loop().time() - start_time < 3.0:
                    try:
                        msg_str = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        msg = json.loads(msg_str)
                        if msg[0] == "EVENT" and msg[1] == "feedo_fetch":
                            fetched_text = msg[2].get("content")
                            source = "proxy_nostr"
                            break
                        elif msg[0] == "EOSE":
                            break
                    except asyncio.TimeoutError:
                        continue
        except Exception as e:
            logger.error(f"Nostr fetch failed for {hash_id} at {post.relay_url}: {e}")
            
    if fetched_text:
        if not is_free:
            await TokenomicsService.reward_query_hit(db, post.author_address, None, fee_amount=cost)
        return {
            "hash_id": post.hash_id,
            "text": fetched_text,
            "author": post.author_address,
            "metadata": post.metadata_,
            "status": "finalized" if post.is_finalized else "mempool",
            "source": source
        }
        
    # Fallback to returning metadata and relay_url
    return {
        "hash_id": post.hash_id,
        "text": None,
        "author": post.author_address,
        "metadata": post.metadata_,
        "relay_url": post.relay_url,
        "status": "finalized" if post.is_finalized else "mempool",
        "source": "metadata_only",
        "warning": "Content not available locally and proxy fetch failed."
    }

@router.get("/status/{hash_id}")
async def get_content_status(hash_id: str, db: AsyncSession = Depends(get_db)):
    """Check publication status (mempool, rejected, finalized)."""
    stmt = select(Post).where(Post.hash_id == hash_id)
    post = (await db.execute(stmt)).scalar_one_or_none()
    
    if not post:
        return {"hash_id": hash_id, "status": "mempool"} # assuming it's in mempool if not found
        

        
    return {
        "hash_id": hash_id,
        "status": "finalized" if post.is_finalized else "mempool"
    }

@router.post("/blob")
async def upload_blob(request: Request, file: UploadFile = File(...), signature: str = Form(...)):
    """Upload heavy media. Returns blob_hash."""
    # TODO: Pass blob to feedo-core for IPFS/Sharded DA storage
        
    file_bytes = await file.read()
    # Mocking actual save and getting hash
    import hashlib
    blob_hash = hashlib.sha256(file_bytes).hexdigest()
    
    # Normally we would store it via upload_manager and announce
    return {"blob_hash": blob_hash, "size": len(file_bytes)}

@router.get("/blob/{blob_hash}")
async def get_blob(blob_hash: str, request: Request, client_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Stream media file. Retrieves from DHT if not in local cache."""
    from tokenomics_service import TokenomicsService
    
    # Tokenomics: Pay-per-download
    download_cost = 5 # arbitrary higher cost for blobs
    if client_id:
        success = await TokenomicsService.pay_for_query(db, client_id, cost=download_cost, allow_free_quota=False)
        if not success:
            raise HTTPException(status_code=402, detail="Insufficient tokens for download.")
            
    cache_root = "/app/db" if os.path.isdir("/app/db") else "./db_data"
    media_dir = os.path.join(cache_root, "media_cache")
    file_path = os.path.join(media_dir, blob_hash)
    
    if os.path.exists(file_path):
        # Local hit: Reward the local node as the storage node
        if client_id:
            import os
            local_pubkey = os.getenv("NODE_WALLET_ADDRESS", "local_node")
            # In a real scenario we need the blob metadata to know the author
            await TokenomicsService.reward_query_hit(db, None, local_pubkey, fee_amount=download_cost)
            
        with open(file_path, "rb") as f:
            return Response(content=f.read(), media_type="application/octet-stream")
            
    # If not found locally, we would query the Rust core
    # For now, just slash a hypothetical failed node
    # await TokenomicsService.slash_node(db, "failed_node", penalty_amount=10)
        
    raise HTTPException(status_code=404, detail="Blob not found in local cache and DA fetch failed")
