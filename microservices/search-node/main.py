import asyncio
import os
import uvicorn
from fastapi import FastAPI, Request
from pydantic import BaseModel
import aiohttp
import json

from vector_service import VectorBrain
from p2p import P2PNetwork
from crawler import SearchCrawler
from storage_adapters import FeedoStorageAdapter, IPFSStorageAdapter

app = FastAPI(title="Search Node")

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
brain = VectorBrain(db_path="./lancedb_data")
p2p_net = None
crawler = None

gateways_env = os.getenv("GATEWAYS", "")
if gateways_env:
    GATEWAYS = [g.strip() for g in gateways_env.split(",") if g.strip()]
else:
    GATEWAYS = [os.getenv("STORAGE_NODE_URL", "http://127.0.0.1:8040")]

async def fetch_missing_text_from_dht(results: list):
    async def fetch_text(r):
        if not r.get("text"):
            async with aiohttp.ClientSession() as session:
                for gateway in GATEWAYS:
                    try:
                        async with session.get(f"{gateway}/download/{r['hash_id']}", timeout=3.0) as resp:
                            if resp.status == 200:
                                raw_data = await resp.read()
                                data = json.loads(raw_data.decode('utf-8'))
                                if isinstance(data, dict):
                                    r["text"] = data.get("text", "")
                                return # Success, break out of fallback loop
                    except Exception as e:
                        pass # try next gateway
    
    tasks = [fetch_text(r) for r in results if not r.get("text")]
    if tasks:
        await asyncio.gather(*tasks)

def get_profiles_batch_from_db(pubkeys: set) -> dict:
    if not pubkeys: return {}
    try:
        author_list = []
        for pk in pubkeys:
            if pk:
                author_list.append(f"'{pk}'")
                author_list.append(f"'did:feedo:schnorr:{pk}'")
        if not author_list:
            return {}
            
        in_clause = ", ".join(author_list)
        where_clause = f"author IN ({in_clause})"
        
        results = brain.table.search().where(where_clause).limit(len(author_list) * 2).to_list()
        
        profiles = {}
        for r in results:
            meta_str = r.get("metadata", "{}")
            if meta_str:
                try:
                    meta = json.loads(meta_str)
                    if meta.get("nostr_kind") == 0:
                        author_did = r.get("author", "")
                        pk = author_did.replace("did:feedo:schnorr:", "")
                        if pk and pk not in profiles:
                            profiles[pk] = meta
                except: pass
        return profiles
    except Exception: pass
    return {}

class HandshakePayload(BaseModel):
    peer_id: str
    centroids: list[list[float]]
    cluster_ids: list[str]

class SearchPayload(BaseModel):
    query: str
    ttl: int = 3

@app.on_event("startup")
async def startup_event():
    global p2p_net, crawler
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "127.0.0.1")
    
    # Initialize P2P Network
    p2p_net = P2PNetwork(brain, host, port)
    asyncio.create_task(p2p_net.broadcast_centroids_loop())
    
    # Initialize Crawler
    adapters = [FeedoStorageAdapter(), IPFSStorageAdapter()]
    crawler = SearchCrawler(brain, adapters)
    asyncio.create_task(crawler.crawl_loop())

@app.post("/p2p/handshake")
async def p2p_handshake(payload: HandshakePayload):
    """Receive centroids from a peer and update the global map."""
    brain.update_global_map(payload.peer_id, payload.centroids, payload.cluster_ids)
    return {"status": "ok"}

@app.get("/query")
async def client_query(text: str, limit: int = 50, federated: bool = True, item_type: str = "all"):
    """Client endpoint expected by feedo-search-ui. Replaces GET /search."""
    # 1. Local Search
    query_vector = await brain.get_embedding_async(text, is_query=True)
    local_results = []
    
    try:
        # We fetch extra to filter post-search if item_type is specified
        records = brain.table.search(query_vector).limit(limit * 2).to_list()
        
        # Batch extract authors to resolve profiles
        unique_pubkeys = set()
        for r in records:
            author_did = r.get("author", "")
            pk = author_did.replace("did:feedo:schnorr:", "") if author_did else ""
            if pk: unique_pubkeys.add(pk)
            r["extracted_pubkey"] = pk
            
        profiles_cache = get_profiles_batch_from_db(unique_pubkeys)
        
        for r in records:
            meta_str = r.get("metadata", "{}")
            meta = json.loads(meta_str) if meta_str else {}
            pubkey = r.get("extracted_pubkey", "")
            
            profile = profiles_cache.get(pubkey, {})
            author_name = profile.get("name") or profile.get("display_name")
            author_avatar = profile.get("picture")
            
            result_data = {
                "hash_id": r.get("hash_id"),
                "item_type": "profile" if meta.get("nostr_kind") == 0 else "post",
                "text": r.get("text", ""),
                "author": pubkey,
                "metadata": meta,
                "published_at": meta.get("nostr_created_at"),
                "score": 1.0 - (r.get("_distance", 0) / 2.0)
            }
            if author_name: result_data["author_name"] = author_name
            if author_avatar: result_data["author_avatar"] = author_avatar
            
            local_results.append(result_data)
    except Exception as e:
        print(f"Error local search: {e}")

    # 2. Federated Search (if requested)
    federated_results = []
    if federated and p2p_net:
        federated_results = await p2p_net.federated_search(query_vector, text, ttl=3, top_k=5)
        # Fix format for federated results if they differ
        for r in federated_results:
            if "item_type" not in r:
                r["item_type"] = "profile" if r.get("metadata", {}).get("nostr_kind") == 0 else "post"
            author_did = r.get("author", "")
            if author_did and author_did.startswith("did:feedo:schnorr:"):
                r["author"] = author_did.replace("did:feedo:schnorr:", "")
    
    # 3. Combine and sort
    all_results = local_results + federated_results
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Deduplicate and filter by item_type
    seen = set()
    final_results = []
    for r in all_results:
        if r["hash_id"] not in seen:
            if item_type == "all" or item_type == r["item_type"]:
                seen.add(r["hash_id"])
                final_results.append(r)
            if len(final_results) >= limit:
                break
                
    await fetch_missing_text_from_dht(final_results)
            
    return {"results": final_results}

@app.get("/feed")
async def get_feed(limit: int = 50, source_type: str = "main", offset: int = 0):
    """Infinite scroll feed endpoint for the UI."""
    # In a real SQL DB, we'd do ORDER BY published_at DESC LIMIT limit OFFSET offset.
    # In LanceDB, if it doesn't support global sorting easily, we simulate it for the prototype.
    try:
        # Just grab recent records. This is a stub for the UI.
        records = brain.table.search().limit(1000).to_list()
        
        parsed_records = []
        for r in records:
            meta_str = r.get("metadata", "{}")
            r["parsed_meta"] = json.loads(meta_str) if meta_str else {}
            parsed_records.append(r)
            
        parsed_records.sort(key=lambda x: x["parsed_meta"].get("nostr_created_at", 0), reverse=True)
        
        feed_candidates = []
        unique_pubkeys = set()
        
        for r in parsed_records[offset:]:
            text_content = r.get("text")
            if not text_content: continue
                
            text_content = text_content.strip()
            is_json_profile = text_content.startswith('{"name":') or text_content.startswith('{"about":') or text_content.startswith('{"picture":')
            
            if r["parsed_meta"].get("nostr_kind") != 0 and not is_json_profile:
                author_did = r.get("author", "")
                pubkey = author_did.replace("did:feedo:schnorr:", "") if author_did else ""
                if pubkey: unique_pubkeys.add(pubkey)
                r["extracted_pubkey"] = pubkey
                feed_candidates.append(r)
                
            if len(feed_candidates) >= limit:
                break
                
        profiles_cache = get_profiles_batch_from_db(unique_pubkeys)
        
        feed = []
        for r in feed_candidates:
            pubkey = r.get("extracted_pubkey", "")
            profile = profiles_cache.get(pubkey, {})
            author_name = profile.get("name") or profile.get("display_name")
            author_avatar = profile.get("picture")
            
            post_data = {
                "hash_id": r.get("hash_id"),
                "item_type": "post",
                "text": r.get("text", ""),
                "author": pubkey,
                "metadata": r["parsed_meta"],
                "published_at": r["parsed_meta"].get("nostr_created_at")
            }
            if author_name: post_data["author_name"] = author_name
            if author_avatar: post_data["author_avatar"] = author_avatar
            
            feed.append(post_data)
                
        await fetch_missing_text_from_dht(feed)
        return feed
    except Exception as e:
        return []

@app.get("/v1/identity/{pubkey}")
async def get_identity(pubkey: str):
    """Fetch user profile from local database."""
    profiles = get_profiles_batch_from_db({pubkey})
    return {"profile": profiles.get(pubkey, {})}

@app.put("/v1/identity/update/{pubkey}")
async def update_identity(pubkey: str, payload: Request):
    """Accepts profile updates from UI and forwards to storage-node."""
    try:
        data = await payload.json()
        meta = data.get("metadata", {})
        
        # Construct synthetic event for storage-node
        import time
        import aiohttp
        
        synthetic_payload = {
            "hash_id": f"profile_{pubkey}_{int(time.time())}",
            "author": f"did:feedo:schnorr:{pubkey}",
            "text": f"User Profile: {meta.get('name','')} {meta.get('about','')}",
            "target_hash": None,
            "signature": data.get("signature", "dummy"),
            "metadata": {
                "nostr_kind": 0,
                "nostr_created_at": int(time.time()),
                "nostr_tags": [],
                **meta
            },
            "ttl_days": 30 # User requested to keep memory low
        }
        
        async with aiohttp.ClientSession() as session:
            for gateway in GATEWAYS:
                try:
                    async with session.post(f"{gateway}/api/v1/ingest/post", json=synthetic_payload, timeout=3.0) as resp:
                        if resp.status == 200:
                            return {"status": "ok"}
                except Exception:
                    pass
        return {"status": "error"}
    except Exception as e:
        print(f"Error updating identity: {e}")
        return {"status": "error"}

@app.get("/v1/node/peers")
async def get_peers():
    """Return list of connected peers for the UI network spider."""
    if p2p_net:
        return {"peers": list(p2p_net.known_peers)}
    return {"peers": []}

@app.get("/explorer/stats")
async def get_explorer_stats():
    """Returns network and indexer statistics for the explorer."""
    try:
        indexed_posts = len(brain.table.search().limit(100000).to_list())
    except Exception:
        indexed_posts = 0
        
    peers_count = len(p2p_net.known_peers) if p2p_net else 0
    active_nodes = peers_count + 1
    
    return {
        "active_nodes": active_nodes,
        "indexed_posts": indexed_posts,
        "network_health": "Healthy" if active_nodes > 1 else "Syncing"
    }

@app.post("/p2p/search")
async def p2p_search(payload: SearchPayload):
    """Peer endpoint. Searches locally and forwards if TTL > 0."""
    result = await client_query(payload.query, limit=10, federated=payload.ttl > 1)
    return {"query": payload.query, "results": result["results"]}

@app.get("/profiles/check")
async def check_profile(pubkey: str):
    """Check if we already have the profile for this pubkey in LanceDB."""
    try:
        profiles = get_profiles_batch_from_db({pubkey})
        return {"exists": bool(profiles.get(pubkey))}
    except Exception:
        return {"exists": False}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
