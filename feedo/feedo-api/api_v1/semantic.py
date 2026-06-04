from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from pydantic import BaseModel
import logging

from database import get_db
from models import Post

logger = logging.getLogger(__name__)

router = APIRouter()

class SemanticQueryRequest(BaseModel):
    text: str
    limit: int = 10
    threshold: float = 0.5
    federated: bool = False

class MempoolValidationRequest(BaseModel):
    tx_hash: str
    originating_node: str
    text: str

@router.post("/validate_uniqueness")
async def validate_uniqueness(req: MempoolValidationRequest, request: Request):
    """
    Internal endpoint for Rust Core.
    Validates if text is semantically unique across the network.
    Used during Global Semantic Consensus before PBFT voting.
    """
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        import main
        brain = main.brain
        if not brain:
            raise HTTPException(status_code=503, detail="Vector search not initialized")
            
    try:
        duplicate_hash = await brain.find_duplicate_async(req.text, threshold=0.90)
        
        if duplicate_hash:
            logger.info(f"PBFT Mempool Submission {req.tx_hash} rejected: semantic_duplicate (similar to {duplicate_hash})")
            return {"valid": False, "reason": "semantic_duplicate", "duplicate_hash": duplicate_hash}
            
        logger.info(f"PBFT Mempool Submission {req.tx_hash} validated successfully (unique)")
        return {"valid": True}
    except Exception as e:
        logger.error(f"Validation error in PBFT consensus: {e}")
        return {"valid": False, "reason": str(e)}

@router.post("/query")
async def semantic_query(req: SemanticQueryRequest, request: Request):
    """Smart search using LanceDB vectors."""
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        # Fallback if brain wasn't attached to state
        import main
        brain = main.brain
        if not brain:
            raise HTTPException(status_code=503, detail="Vector search not initialized")
            
    results = []
    # Using the synchronous brain operations in threadpool or directly
    try:
        vec = await brain.get_embedding_async(req.text)
        search_res = brain.table.search(vec).metric("cosine").limit(req.limit).to_list()
        
        for r in search_res:
            dist = r.get("_distance", 1.0)
            if dist <= (1.0 - req.threshold):  # rough translation of threshold
                results.append({
                    "hash_id": r.get("hash_id"),
                    "post_id": r.get("post_id"),
                    "score": 1.0 - dist
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    if req.federated:
        target_peers = brain.route_query(vec, top_k=3)
        if target_peers:
            logger.info(f"🌐 Routing federated query to Supernodes: {target_peers}")
            import httpx
            import os
            rust_url = os.environ.get("RUST_CORE_URL", "http://127.0.0.1:8041/local/publish").replace("/local/publish", "/local/vector_route_query")
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(rust_url, json={
                        "vector": vec,
                        "target_peers": target_peers,
                        "limit": req.limit
                    }, timeout=15.0)
                    if resp.status_code == 200:
                        remote_results = resp.json().get("results", [])
                        # Merge local and remote
                        results.extend(remote_results)
                        # Sort by score descending and deduplicate by hash_id
                        seen = set()
                        unique_results = []
                        for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
                            if r["hash_id"] not in seen:
                                seen.add(r["hash_id"])
                                unique_results.append(r)
                        results = unique_results[:req.limit]
            except Exception as e:
                logger.warning(f"⚠️ Failed to query remote Supernodes via Rust: {e}")
    
    return {"results": results}

@router.get("/cluster/{hash_id}")
async def semantic_cluster(hash_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Deduplication in action. Find all posts with similar vectors."""
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        import main
        brain = main.brain
        if not brain:
             raise HTTPException(status_code=503, detail="Vector search not initialized")

    try:
        # Find the vector for the given hash_id
        target = brain.table.search().where(f"hash_id = '{hash_id}'").limit(1).to_list()
        if not target:
            raise HTTPException(status_code=404, detail="Vector for hash_id not found")
            
        vec = target[0]["vector"]
        # Search for similar vectors
        search_res = brain.table.search(vec).metric("cosine").limit(20).to_list()
        
        cluster = []
        for r in search_res:
            dist = r.get("_distance", 1.0)
            if dist < 0.15: # Highly similar
                cluster.append(r.get("hash_id"))
                
        return {"cluster": cluster}
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@router.post("/feed")
async def semantic_feed(liked_hashes: List[str], request: Request):
    """Generate personalized feed based on liked hashes."""
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        import main
        brain = main.brain
        if not brain:
             raise HTTPException(status_code=503, detail="Vector search not initialized")

    try:
        # Fetch vectors for all liked hashes
        vectors = []
        for h in liked_hashes:
            res = brain.table.search().where(f"hash_id = '{h}'").limit(1).to_list()
            if res:
                vectors.append(res[0]["vector"])
                
        if not vectors:
            return {"feed": []}
            
        # Compute centroid (average vector)
        import numpy as np
        centroid = np.mean(vectors, axis=0).tolist()
        
        # Search using centroid
        search_res = brain.table.search(centroid).metric("cosine").limit(50).to_list()
        feed = [r.get("hash_id") for r in search_res if r.get("hash_id") not in liked_hashes]
        
        return {"feed": feed}
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@router.get("/namespace/{namespace_name}")
async def semantic_namespace(namespace_name: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Get all data from a specific namespace (e.g. feedo/tech/rust)."""
    # Assuming namespace is stored in post metadata JSON
    # PostgreSQL JSONB query
    stmt = select(Post).where(Post.metadata_.contains({"namespace": namespace_name}))
    posts = (await db.execute(stmt)).scalars().all()
    
    return {"namespace": namespace_name, "posts": [{"hash_id": p.hash_id, "text": p.text_content} for p in posts]}
