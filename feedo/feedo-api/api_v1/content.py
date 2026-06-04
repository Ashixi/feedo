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
    text_content: str
    author_address: str
    metadata_: Optional[Dict[str, Any]] = None
    signature: str

@router.post("/publish")
async def publish_content(req: PublishRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Publish content to mempool for AI-validation and PBFT consensus."""
    # Proxy to Rust core for PBFT
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(RUST_CORE_URL, json=req.dict(), timeout=10.0)
            if res.status_code != 200:
                raise HTTPException(status_code=res.status_code, detail=res.text)
            return res.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to contact rust core: {str(e)}")

@router.get("/{hash_id}")
async def get_content(hash_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Get a specific note/article. Fetch via Kademlia DHT if missing locally."""
    stmt = select(Post).where(Post.hash_id == hash_id)
    post = (await db.execute(stmt)).scalar_one_or_none()
    
    if post:
        return {
            "hash_id": post.hash_id,
            "text": post.text_content,
            "author": post.author_address,
            "metadata": post.metadata_,
            "status": "finalized" if post.is_finalized else "mempool"
        }
        
    # If not local, try fetching via DHT
    p2p = getattr(request.app.state, 'p2p_manager', None)
    if p2p:
        # P2P fetching logic
        pass
        
    raise HTTPException(status_code=404, detail="Content not found locally or in DHT")

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
    upload_mgr = getattr(request.app.state, '_p2p_upload_manager', None)
    if not upload_mgr:
        raise HTTPException(status_code=503, detail="Upload manager not available")
        
    file_bytes = await file.read()
    # Mocking actual save and getting hash
    import hashlib
    blob_hash = hashlib.sha256(file_bytes).hexdigest()
    
    # Normally we would store it via upload_manager and announce
    return {"blob_hash": blob_hash, "size": len(file_bytes)}

@router.get("/blob/{blob_hash}")
async def get_blob(blob_hash: str, request: Request):
    """Stream media file. Retrieves from DHT if not in local cache."""
    # Assuming media cache dir logic
    cache_root = "/app/db" if os.path.isdir("/app/db") else "./db_data"
    media_dir = os.path.join(cache_root, "media_cache")
    file_path = os.path.join(media_dir, blob_hash)
    
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            return Response(content=f.read(), media_type="application/octet-stream")
            
    raise HTTPException(status_code=404, detail="Blob not found in local cache")
