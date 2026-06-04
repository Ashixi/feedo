from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from pydantic import BaseModel

from database import get_db
from models import Edge, Post

router = APIRouter()

class EdgeRequest(BaseModel):
    source_hash: str
    target_hash: str
    edge_type: str
    signature: str
    author_address: str

@router.post("/edge")
async def create_edge(req: EdgeRequest, db: AsyncSession = Depends(get_db)):
    """Create a signed relationship between two pieces of content."""
    # Normally verify signature here
    # verify_signature(req.author_address, payload, req.signature)
    
    edge = Edge(
        source_hash=req.source_hash,
        target_hash=req.target_hash,
        edge_type=req.edge_type,
        signature=req.signature,
        author_address=req.author_address.lower()
    )
    db.add(edge)
    await db.commit()
    return {"status": "success", "edge_id": edge.id}

@router.get("/edges/outbound/{hash_id}")
async def get_outbound_edges(hash_id: str, db: AsyncSession = Depends(get_db)):
    """What does this article link to?"""
    stmt = select(Edge).where(Edge.source_hash == hash_id)
    edges = (await db.execute(stmt)).scalars().all()
    return {"outbound": [{"target_hash": e.target_hash, "type": e.edge_type} for e in edges]}

@router.get("/edges/inbound/{hash_id}")
async def get_inbound_edges(hash_id: str, db: AsyncSession = Depends(get_db)):
    """Who links to this article? (Reverse links for PageRank)"""
    stmt = select(Edge).where(Edge.target_hash == hash_id)
    edges = (await db.execute(stmt)).scalars().all()
    return {"inbound": [{"source_hash": e.source_hash, "type": e.edge_type} for e in edges]}

@router.get("/tree/{hash_id}")
async def get_tree(hash_id: str, db: AsyncSession = Depends(get_db)):
    """Returns the full discussion tree using recursive lookup."""
    # A simple breadth-first search implementation in python (better to use CTE in prod)
    visited = set()
    queue = [hash_id]
    tree = []
    
    while queue:
        current_hash = queue.pop(0)
        if current_hash in visited:
            continue
        visited.add(current_hash)
        
        stmt = select(Edge).where(Edge.target_hash == current_hash)
        inbound_edges = (await db.execute(stmt)).scalars().all()
        
        for e in inbound_edges:
            tree.append({
                "source": e.source_hash,
                "target": e.target_hash,
                "type": e.edge_type
            })
            queue.append(e.source_hash)
            
    return {"tree": tree}
