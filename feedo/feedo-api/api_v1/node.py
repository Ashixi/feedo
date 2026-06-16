from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from pydantic import BaseModel
import secrets
import hashlib
import psutil

from database import get_db
from models import ApiKey, ApiKeyRole, Post

router = APIRouter()

class CreateCommercialKeyRequest(BaseModel):
    name: str
    owner_address: str

@router.get("/health")
async def get_node_health(request: Request, db: AsyncSession = Depends(get_db)):
    """Status of Rust and Python connections."""
    health = {
        "python_api": "ok",
        "database": "unknown",
        "p2p": "unknown",
        "vector_db": "unknown"
    }
    
    # DB Check
    try:
        await db.execute(select(1))
        health["database"] = "ok"
    except Exception:
        health["database"] = "error"
        
    # P2P Check
    health["p2p"] = "managed_by_rust_core"
        
    # Vector DB Check
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        import main
        brain = main.brain
    if brain:
        try:
            brain.table.count_rows()
            health["vector_db"] = "ok"
        except Exception:
            health["vector_db"] = "error"
            
    return health

@router.get("/metrics")
async def get_node_metrics(request: Request, db: AsyncSession = Depends(get_db)):
    """System metrics and P2P stats."""
    cpu_usage = psutil.cpu_percent(interval=None)
    ram_usage = psutil.virtual_memory().percent
    
    total_posts = await db.scalar(select(func.count(Post.id)))
    
    p2p_peers = 0 # TODO: Fetch from Rust core
        
    return {
        "cpu_percent": cpu_usage,
        "ram_percent": ram_usage,
        "total_posts": total_posts,
        "p2p_peers": p2p_peers
    }

@router.get("/peers")
async def get_peers(request: Request):
    """List all connected gossipsub peers."""
    # TODO: Fetch from Rust core via HTTP
    return {"peers": []}

@router.post("/commercial/api_key")
async def create_commercial_key(req: CreateCommercialKeyRequest, db: AsyncSession = Depends(get_db)):
    """Create a paid API key for Web2 startups to query this node."""
    # Note: Authorization to create commercial keys would be required in production
    
    raw_key = secrets.token_urlsafe(32)
    hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
    
    new_api_key = ApiKey(
        hashed_key=hashed_key,
        name=req.name,
        role=ApiKeyRole.PROVIDER,
        owner_address=req.owner_address.lower()
    )
    
    db.add(new_api_key)
    await db.commit()
    
    return {
        "status": "created",
        "api_key": raw_key, # Send raw key only once!
        "owner": req.owner_address
    }

@router.get("/network/sync_state/{source_type}")
async def get_network_sync_state(source_type: str, db: AsyncSession = Depends(get_db)):
    """Return local max timestamp for a source type to help new nodes sync cursor."""
    stmt_last_post = select(func.max(Post.published_at)).where(Post.source_type == source_type)
    last_post_date = (await db.execute(stmt_last_post)).scalar()
    
    timestamp = 0
    if last_post_date:
        import datetime
        if last_post_date.tzinfo is None:
            last_post_date = last_post_date.replace(tzinfo=datetime.timezone.utc)
        timestamp = int(last_post_date.timestamp())
        
    return {
        "source_type": source_type,
        "max_timestamp": timestamp
    }
