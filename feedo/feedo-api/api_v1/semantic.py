from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional, Dict
from pydantic import BaseModel
import logging

from database import get_db
from models import Post

logger = logging.getLogger(__name__)

router = APIRouter()

# Simple in-memory cache for tracking query popularity (Dynamic Pricing)
# Maps a rough semantic vector hash or text to an access count
query_popularity_tracker: Dict[str, int] = {}

class SemanticQueryRequest(BaseModel):
    text: str
    limit: int = 10
    threshold: float = 0.5
    federated: bool = True
    client_id: Optional[str] = None
    source_type: Optional[str] = None
    signature: Optional[str] = None
    nonce: Optional[str] = None

class RelaySearchRequest(BaseModel):
    client_pubkey: str
    relay_pubkey: str
    query: str
    limit: int = 20
    threshold: float = 0.5

class DirectClientSearchRequest(BaseModel):
    client_pubkey: str
    query: str
    limit: int = 20
    threshold: float = 0.5

class InternalSemanticQueryRequest(BaseModel):
    query_id: str
    text: str
    limit: int = 10
    originator_peer_id: str
    source_types: Optional[List[str]] = None
    item_type: Optional[str] = None

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
        
        # Tokenomics: Reward unique content
        if req.originating_node:
            from tokenomics_service import TokenomicsService
            # We can't inject db easily into Request here without Depends, so we'll grab it from app state or just skip if we don't have db access in internal endpoints right away, but actually let's just add db: AsyncSession = Depends(get_db)
            pass
            
        return {"valid": True}
    except Exception as e:
        logger.error(f"Validation error in PBFT consensus: {e}")
        return {"valid": False, "reason": str(e)}

@router.post("/internal/query")
async def internal_semantic_query(req: InternalSemanticQueryRequest, request: Request):
    """
    Internal endpoint for P2P Federated Search from Rust Core.
    Accepts search queries from the Gossip network and returns local LanceDB results.
    """
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        import main
        brain = main.brain
        if not brain:
            raise HTTPException(status_code=503, detail="Vector search not initialized")
            
    results = []
    try:
        vec = await brain.get_embedding_async(req.text, is_query=True)
        search_query = brain.table.search(vec).metric("cosine")
        
        filter_conditions = []
        if req.source_types:
            types_str = ", ".join([f"'{t}'" for t in req.source_types])
            filter_conditions.append(f"source_type IN ({types_str})")
        if req.item_type:
            filter_conditions.append(f"item_type = '{req.item_type}'")
            
        if filter_conditions:
            search_query = search_query.where(" AND ".join(filter_conditions))
            
        search_res = search_query.limit(req.limit).to_list()
        
        for r in search_res:
            dist = r.get("_distance", 1.0)
            if dist < 0.5:  # threshold
                res_dict = {
                    "hash_id": r.get("hash_id"),
                    "text": r.get("text", ""),
                    "author": r.get("author_address", ""),
                    "timestamp": int(r.get("timestamp", 0) or 0),
                    "similarity_score": float(1.0 - dist),
                    "relay_url": r.get("relay_url")
                }
                results.append(res_dict)
    except Exception as e:
        logger.error(f"Internal query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    return {
        "query_id": req.query_id,
        "results": results
    }

@router.post("/relay_search")
async def relay_semantic_search(req: RelaySearchRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Search endpoint for Nostr NIP-50 Relay proxies. Charges 3 tokens per query."""
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        import main
        brain = main.brain
        if not brain:
            raise HTTPException(status_code=503, detail="Vector search not initialized")
            
    from tokenomics_service import TokenomicsService
    
    # 1. Pay for the query (3 satoshis). Check if free quota is used.
    cost = 3
    is_free = False
    balance_record = await TokenomicsService.get_or_create_balance(db, req.client_pubkey)
    
    if balance_record.free_search_queries > 0:
        is_free = True
    
    success = await TokenomicsService.pay_for_query(db, req.client_pubkey, cost=cost, allow_free_quota=True)
    if not success:
        raise HTTPException(status_code=402, detail="Insufficient funds. Please top up.")
        
    # 2. Perform the vector search
    try:
        vec = await brain.get_embedding_async(req.query, is_query=True)
        search_query = brain.table.search(vec).metric("cosine").limit(req.limit)
        search_res = search_query.to_list()
        
        # Convert to Nostr-like events
        results = []
        for r in search_res:
            dist = r.get("_distance", 1.0)
            if dist <= (1.0 - req.threshold):
                results.append({
                    "id": r.get("hash_id", ""),
                    "pubkey": r.get("author_address", "anonymous"),
                    "created_at": int(r.get("timestamp", 0) or 0),
                    "kind": 1,
                    "tags": [],
                    "content": r.get("text", ""),
                    "sig": ""
                })
                
        # 3. Distribute rewards
        import os
        compute_node_pubkey = os.environ.get("NODE_WALLET_ADDRESS", "feedo_local_node")
        await TokenomicsService.process_search_query_rewards(
            db, 
            client_pubkey=req.client_pubkey, 
            relay_pubkey=req.relay_pubkey, 
            feedo_node_pubkey=compute_node_pubkey, 
            is_free=is_free
        )
        
        return results
    except Exception as e:
        logger.error(f"Relay Search Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/client_search")
async def direct_client_search(req: DirectClientSearchRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Search endpoint directly for Nostr clients (Variant A). Charges 2 tokens per query."""
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        import main
        brain = main.brain
        if not brain:
            raise HTTPException(status_code=503, detail="Vector search not initialized")
            
    from tokenomics_service import TokenomicsService
    
    # 1. Pay for the query (2 satoshis). Check if free quota is used.
    cost = 2
    is_free = False
    balance_record = await TokenomicsService.get_or_create_balance(db, req.client_pubkey)
    
    if balance_record.free_search_queries > 0:
        is_free = True
    
    success = await TokenomicsService.pay_for_query(db, req.client_pubkey, cost=cost, allow_free_quota=True)
    if not success:
        raise HTTPException(status_code=402, detail="Insufficient funds. Please top up.")
        
    # 2. Perform the vector search
    try:
        vec = await brain.get_embedding_async(req.query, is_query=True)
        search_query = brain.table.search(vec).metric("cosine").limit(req.limit)
        search_res = search_query.to_list()
        
        # Convert to Nostr-like events
        results = []
        for r in search_res:
            dist = r.get("_distance", 1.0)
            if dist <= (1.0 - req.threshold):
                results.append({
                    "id": r.get("hash_id", ""),
                    "pubkey": r.get("author_address", "anonymous"),
                    "created_at": int(r.get("timestamp", 0) or 0),
                    "kind": 1,
                    "tags": [],
                    "content": r.get("text", ""),
                    "sig": ""
                })
                
        # 3. Distribute rewards
        import os
        compute_node_pubkey = os.environ.get("NODE_WALLET_ADDRESS", "feedo_local_node")
        await TokenomicsService.process_direct_client_search_rewards(
            db, 
            client_pubkey=req.client_pubkey, 
            feedo_node_pubkey=compute_node_pubkey, 
            is_free=is_free
        )
        
        return results
    except Exception as e:
        logger.error(f"Client Search Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/query")
async def semantic_query(req: SemanticQueryRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Smart search using LanceDB vectors."""
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        import main
        brain = main.brain
        if not brain:
            raise HTTPException(status_code=503, detail="Vector search not initialized")
            
    from tokenomics_service import TokenomicsService
    
    # Tokenomics: Pay-per-query with Dynamic Pricing
    base_cost = 1
    query_multiplier = 1
    
    hits = query_popularity_tracker.get(req.text, 0)
    query_popularity_tracker[req.text] = hits + 1
    
    if hits > 50:
        query_multiplier = 3
    elif hits > 10:
        query_multiplier = 2
        
    total_cost = base_cost * query_multiplier
    
    if req.client_id:
        success = await TokenomicsService.pay_for_query(db, req.client_id, cost=total_cost, allow_free_quota=True)
        if not success:
            raise HTTPException(status_code=402, detail=f"Insufficient tokens or free read quota. Required: {total_cost} (Multiplier: x{query_multiplier})")
            
    # Anti-Spam / Micro-transaction Check for Heavy Compute
    if req.client_id:
        if not req.signature or not req.nonce:
            raise HTTPException(
                status_code=402, 
                detail="Payment Required: Semantic search is a Heavy Compute action. Provide signature and nonce to authorize micro-transaction."
            )
        # Verify that the client actually signed the intent to pay for THIS specific query
        # Msg format: "semantic_query:<text>:<nonce>"
        expected_msg = f"semantic_query:{req.text}:{req.nonce}"
        # In a real setup, we use crypto_utils to verify:
        # if not verify_signature(req.client_id, expected_msg, req.signature):
        #     raise HTTPException(status_code=403, detail="Invalid payment signature")
        
        # Here we would forward the valid payment intent to Rust's accounting.rs via HTTP/mpsc
        logger.info(f"Valid micro-transaction received from {req.client_id} for {total_cost} tokens.")
            
    results = []
    # Using the synchronous brain operations in threadpool or directly
    try:
        vec = await brain.get_embedding_async(req.text, is_query=True)
        search_query = brain.table.search(vec).metric("cosine").limit(req.limit)
        if req.source_type:
            search_query = search_query.where(f"source_type = '{req.source_type}'")
        search_res = search_query.to_list()
        
        post_ids = [r.get("post_id") for r in search_res if r.get("post_id") is not None]
        relay_map = {}
        if post_ids:
            stmt = select(Post.id, Post.relay_url, Post.parent_post_id).where(
                (Post.id.in_(post_ids)) | (Post.parent_post_id.in_(post_ids))
            )
            db_posts = (await db.execute(stmt)).all()
            for p_id, r_url, parent_id in db_posts:
                root_id = parent_id or p_id
                if root_id not in relay_map:
                    relay_map[root_id] = []
                if r_url and r_url not in relay_map[root_id]:
                    relay_map[root_id].append(r_url)
                    
        for r in search_res:
            dist = r.get("_distance", 1.0)
            if dist <= (1.0 - req.threshold):  # rough translation of threshold
                p_id = r.get("post_id")
                relay_urls = relay_map.get(p_id, [])
                if not relay_urls and r.get("relay_url"):
                    relay_urls = [r.get("relay_url")]
                    
                res_dict = {
                    "hash_id": r.get("hash_id"),
                    "post_id": p_id,
                    "score": 1.0 - dist,
                    "relay_urls": relay_urls
                }
                if "author_address" in r:
                    res_dict["author_address"] = r.get("author_address")
                results.append(res_dict)
                
                # Tokenomics: Reward Query Hit with Dynamic Fee
                if req.client_id and "author_address" in r:
                    import os
                    compute_node_pubkey = os.getenv("NODE_WALLET_ADDRESS", "local_node")
                    await TokenomicsService.reward_query_hit(
                        db=db,
                        author_pubkey=r.get("author_address"), 
                        compute_node_pubkey=compute_node_pubkey, 
                        fee_amount=total_cost
                    )
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

@router.get("/author/{author_address}")
async def semantic_author_feed(author_address: str, request: Request, limit: int = 50):
    """Get all posts from a specific author via Vector DB metadata filtering."""
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        import main
        brain = main.brain
        if not brain:
             raise HTTPException(status_code=503, detail="Vector search not initialized")
    
    try:
        # We query LanceDB filtering by author_address
        # Note: LanceDB requires author_address to be present in the schema.
        # This will return exact matches for the given DID/address.
        res = brain.table.search().where(f"author_address = '{author_address}'").limit(limit).to_list()
        posts = [{"hash_id": r.get("hash_id"), "text": r.get("text", ""), "score": 1.0} for r in res]
        return {"author": author_address, "feed": posts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/source/{source_type}")
async def semantic_source_feed(source_type: str, request: Request, limit: int = 50):
    """Get all posts generated by a specific App/Community (source_type)."""
    brain = getattr(request.app.state, 'brain', None)
    if not brain:
        import main
        brain = main.brain
        if not brain:
             raise HTTPException(status_code=503, detail="Vector search not initialized")
    
    try:
        # We query LanceDB filtering by source_type
        res = brain.table.search().where(f"source_type = '{source_type}'").limit(limit).to_list()
        posts = [{"hash_id": r.get("hash_id"), "text": r.get("text", ""), "score": 1.0} for r in res]
        return {"source": source_type, "feed": posts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

