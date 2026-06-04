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
    p2p = getattr(request.app.state, 'p2p_manager', None)
    if p2p:
        health["p2p"] = "ok"
        
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
    
    p2p_peers = 0
    p2p = getattr(request.app.state, 'p2p_manager', None)
    if p2p and hasattr(p2p, "peer_registry"):
        p2p_peers = len(p2p.peer_registry.peers)
        
    return {
        "cpu_percent": cpu_usage,
        "ram_percent": ram_usage,
        "total_posts": total_posts,
        "p2p_peers": p2p_peers
    }

@router.get("/peers")
async def get_peers(request: Request):
    """List all connected gossipsub peers."""
    p2p = getattr(request.app.state, 'p2p_manager', None)
    if not p2p or not hasattr(p2p, "peer_registry"):
        return {"peers": []}
        
    peers_info = []
    for peer_id, info in p2p.peer_registry.peers.items():
        peers_info.append({
            "peer_id": peer_id,
            "pubkey": info.get("pubkey"),
            "last_seen": info.get("last_seen"),
            "is_supernode": info.get("is_supernode", False)
        })
        
    return {"peers": peers_info}

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
