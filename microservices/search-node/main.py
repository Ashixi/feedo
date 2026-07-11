import asyncio
import os
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import Response, JSONResponse
import zipfile
import tempfile
import shutil
from bs4 import BeautifulSoup
from pydantic import BaseModel
import aiohttp
import httpx
import json
from collections import defaultdict

from vector_service import VectorBrain
from p2p import P2PNetwork
from crawler import SearchCrawler
from storage_adapters import FeedoStorageAdapter, IPFSStorageAdapter
import time

app = FastAPI(title="Search Node")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

lance_db_path = os.getenv("LANCE_DB_PATH", "./lancedb_data")
brain = VectorBrain(db_path=lance_db_path)
p2p_net = None
crawler = None

gateways_env = os.getenv("GATEWAYS", "")
if gateways_env:
    GATEWAYS = [g.strip() for g in gateways_env.split(",") if g.strip()]
else:
    GATEWAYS = [os.getenv("STORAGE_NODE_URL", "http://127.0.0.1:8040")]


# --- In-memory Token Bucket Rate Limiter ---
class TokenBucketRateLimiter:
    """Per-path token bucket rate limiter with configurable rates."""
    
    def __init__(self):
        # path -> (tokens, last_refill_timestamp)
        self._buckets = {}
        # Default rates per path (tokens/sec, bucket_capacity)
        self._rate_config = {
            "/query": (100.0, 100.0),
            "/index_document": (50.0, 50.0),
            "/p2p/search": (200.0, 200.0),
            "/p2p/index_vector": (200.0, 200.0),
        }
        # Default for unconfigured paths
        self._default_rate = (50.0, 50.0)
    
    def consume(self, path: str, tokens: float = 1.0) -> bool:
        """Try to consume tokens. Returns True if allowed, False if rate limited."""
        rate, capacity = self._rate_config.get(path, self._default_rate)
        
        if path not in self._buckets:
            # Start with a full bucket
            self._buckets[path] = [capacity, time.monotonic()]
        
        bucket = self._buckets[path]
        current_tokens, last_refill = bucket
        
        now = time.monotonic()
        elapsed = now - last_refill
        
        # Refill tokens based on elapsed time
        current_tokens = min(capacity, current_tokens + elapsed * rate)
        last_refill = now
        
        if current_tokens >= tokens:
            current_tokens -= tokens
            bucket[0] = current_tokens
            bucket[1] = last_refill
            return True
        
        bucket[0] = current_tokens
        bucket[1] = last_refill
        return False


_rate_limiter = TokenBucketRateLimiter()


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limiting to API endpoints."""
    path = request.url.path
    
    # Only rate-limit specific endpoints
    if path in ("/query", "/index_document", "/p2p/search", "/p2p/index_vector"):
        if not _rate_limiter.consume(path):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."}
            )
    
    response = await call_next(request)
    return response


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
                                return
                    except Exception:
                        pass
    tasks = [fetch_text(r) for r in results if not r.get("text")]
    if tasks:
        await asyncio.gather(*tasks)

class HandshakePayload(BaseModel):
    peer_id: str
    centroids: list[list[float]]
    cluster_ids: list[str]

class SearchPayload(BaseModel):
    query: str
    ttl: int = 3

class IndexDocumentPayload(BaseModel):
    hash_id: str
    author: str = ""
    text: str = ""
    item_type: str = "document"
    metadata: dict = {}

class IndexVectorPayload(BaseModel):
    """Payload for /p2p/index_vector — receive a pre-computed vector from a peer node."""
    post_id: int
    hash_id: str
    vector: list[float]
    text: str = ""
    source_type: str = "pubsub"
    item_type: str = "text"
    author: str = ""
    metadata: str = ""

@app.on_event("startup")
async def startup_event():
    global p2p_net, crawler
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "127.0.0.1")
    
    p2p_net = P2PNetwork(brain, host, port)
    asyncio.create_task(p2p_net.broadcast_centroids_loop())

    # Create shared HTTP client for shard vector forwarding
    _http_client = httpx.AsyncClient(timeout=float(os.getenv("SHARD_FORWARD_TIMEOUT", "5.0")))

    adapters = [FeedoStorageAdapter(), IPFSStorageAdapter()]
    crawler = SearchCrawler(brain, adapters, http_client=_http_client)
    asyncio.create_task(crawler.crawl_loop())

@app.post("/p2p/handshake")
async def p2p_handshake(payload: HandshakePayload):
    brain.update_global_map(payload.peer_id, payload.centroids, payload.cluster_ids)
    if p2p_net and payload.peer_id:
        p2p_net.known_peers.add(payload.peer_id)

    # Peer Exchange: return our known peers so the sender can discover the rest of the network
    known_peers_list = list(p2p_net.known_peers) if p2p_net else []
    other_peers = [p for p in known_peers_list if p != payload.peer_id]
    return {"status": "ok", "peers": other_peers}

@app.get("/query")
async def client_query(text: str, limit: int = 50, federated: bool = True, item_type: str = "all", offset: int = 0):
    query_vector = await brain.get_embedding_async(text, is_query=True)
    local_results = []
    
    try:
        fetch_limit = (limit + offset) * 5
        def search_lance_vector(qv, flimit):
            if item_type != "all":
                return brain.table.search(qv, vector_column_name="vector").where(f"item_type = '{item_type}'").limit(flimit).to_list()
            return brain.table.search(qv, vector_column_name="vector").limit(flimit).to_list()
            
        records = await asyncio.to_thread(search_lance_vector, query_vector, fetch_limit)
        
        for r in records:
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try: meta = json.loads(meta) if meta else {}
                except: meta = {}
                
            r_item_type = r.get("item_type", "document")
            
            result_data = {
                "hash_id": r.get("hash_id"),
                "item_type": r_item_type,
                "text": r.get("text", ""),
                "author": r.get("author", ""),
                "metadata": meta,
                "score": 1.0 - (r.get("_distance", 0) / 2.0)
            }
            local_results.append(result_data)
    except Exception as e:
        print(f"Error local search: {e}")
        return {"results": [], "error": str(e)}

    federated_results = []
    if federated and p2p_net:
        try:
            federated_results = await asyncio.wait_for(
                p2p_net.federated_search(query_vector, text, ttl=3, top_k=5),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            print(f"⚠️ Federated search timed out after 2s for query: {text[:80]}")
        except Exception as e:
            print(f"⚠️ Federated search error: {e}")
    
    all_results = local_results + federated_results
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Group duplicates by hash_id instead of discarding them
    seen = {}  # hash_id -> index in final_results
    final_results = []
    for r in all_results:
        hid = r["hash_id"]
        if item_type != "all" and item_type != r.get("item_type", ""):
            continue

        if hid in seen:
            # Duplicate: add to the primary record's duplicates list
            idx = seen[hid]
            primary = final_results[idx]
            if "duplicates" not in primary:
                primary["duplicates"] = []
            # Extract readable URL info for the duplicate
            dup_meta = r.get("metadata", {}) or {}
            if isinstance(dup_meta, str):
                try: dup_meta = json.loads(dup_meta)
                except: dup_meta = {}
            primary["duplicates"].append({
                "hash_id": hid,
                "domain": dup_meta.get("domain", ""),
                "url": dup_meta.get("url", ""),
                "source_type": r.get("source_type", ""),
                "text": (r.get("text") or "")[:300],
                "metadata": dup_meta,
            })
            # Promote duplicate to primary if it has richer metadata
            primary_meta = primary.get("metadata", {}) or {}
            if isinstance(primary_meta, str):
                try: primary_meta = json.loads(primary_meta)
                except: primary_meta = {}
            if (not primary_meta.get("title") and dup_meta.get("title")) or \
               (not primary_meta.get("description") and dup_meta.get("description")) or \
               (not primary_meta.get("domain") and dup_meta.get("domain")):
                # Swap: duplicate becomes primary, primary becomes duplicate
                old_primary = dict(final_results[idx])
                # Keep the duplicate's hash_id but carry over primary data
                final_results[idx] = dict(r)
                final_results[idx]["duplicates"] = [{
                    "hash_id": hid,
                    "domain": primary_meta.get("domain", ""),
                    "url": primary_meta.get("url", ""),
                    "source_type": old_primary.get("source_type", ""),
                    "text": (old_primary.get("text") or "")[:300],
                    "metadata": primary_meta,
                }] + final_results[idx].get("duplicates", [])
        else:
            seen[hid] = len(final_results)
            final_results.append(r)

        if len(final_results) >= limit + offset:
            break

    final_results = final_results[offset:]
    await fetch_missing_text_from_dht(final_results)
    # Also fetch text for duplicates
    for r in final_results:
        for dup in r.get("duplicates", []):
            if not dup.get("text"):
                dup["text"] = r.get("text", "")

    return {"results": final_results}

@app.get("/documents")
async def get_documents(limit: int = 50, offset: int = 0, item_type: str = "all"):
    """Generic endpoint to fetch latest indexed documents."""
    try:
        def search_recent():
            return brain.table.search().limit(1000).to_list()
            
        records = await asyncio.to_thread(search_recent)
        
        parsed_records = []
        for r in records:
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try: meta = json.loads(meta) if meta else {}
                except: meta = {}
            r_item_type = r.get("item_type", "document")
            
            if item_type != "all" and item_type != r_item_type:
                continue
                
            parsed_records.append({
                "hash_id": r.get("hash_id"),
                "item_type": r_item_type,
                "text": r.get("text", ""),
                "author": r.get("author", ""),
                "metadata": meta,
                "timestamp": r.get("timestamp", 0)
            })
            
        parsed_records.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        
        final_docs = parsed_records[offset:offset+limit]
        await fetch_missing_text_from_dht(final_docs)
        return {"results": final_docs}
    except Exception as e:
        print("Error in /documents:", e)
        return {"results": []}

@app.post("/index_document")
async def index_document(payload: IndexDocumentPayload):
    """Manually push a document or website metadata to be indexed."""
    try:
        await brain.add_vector_async(
            post_id=int(time.time()), 
            hash_id=payload.hash_id, 
            text=payload.text,
            item_type=payload.item_type,
            author=payload.author,
            metadata=json.dumps(payload.metadata) if isinstance(payload.metadata, dict) else payload.metadata
        )
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/v1/node/peers")
async def get_peers():
    if p2p_net:
        return {"peers": list(p2p_net.known_peers)}
    return {"peers": []}

@app.get("/explorer/stats")
async def get_explorer_stats():
    try:
        def get_stats():
            return len(brain.table)
        indexed_posts = await asyncio.to_thread(get_stats)
    except Exception:
        indexed_posts = 0
        
    peers_count = len(p2p_net.known_peers) if p2p_net else 0
    active_nodes = peers_count + 1
    
    return {
        "active_nodes": active_nodes,
        "indexed_posts": indexed_posts,
        "network_health": "Healthy" if active_nodes > 1 else "Syncing"
    }

@app.post("/proxy/publish")
async def proxy_publish(file: UploadFile = File(...)):
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files are supported")
    
    pinata_api_key = os.getenv("PINATA_API_KEY")
    pinata_secret = os.getenv("PINATA_SECRET_API_KEY")
    
    if not pinata_api_key or not pinata_secret:
        raise HTTPException(status_code=500, detail="Pinata API keys not configured on server")
        
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, "upload.zip")
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        
        with open(zip_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
            
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
            
        root_items = os.listdir(extract_dir)
        if len(root_items) == 1 and os.path.isdir(os.path.join(extract_dir, root_items[0])):
            extract_dir = os.path.join(extract_dir, root_items[0])
            
        title = "Unknown Site"
        description = ""
        text_content = ""
        index_path = os.path.join(extract_dir, "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                html_content = f.read()
                soup = BeautifulSoup(html_content, 'html.parser')
                if soup.title:
                    title = soup.title.string
                meta_desc = soup.find("meta", {"name": "description"})
                if meta_desc and meta_desc.get("content"):
                    description = meta_desc["content"]
                text_content = soup.get_text(separator=' ', strip=True)
                
        url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
        headers = {
            "pinata_api_key": pinata_api_key,
            "pinata_secret_api_key": pinata_secret
        }
        
        import requests
        files = []
        open_files = []
        try:
            for root, _, files_in_dir in os.walk(extract_dir):
                for f_name in files_in_dir:
                    file_path = os.path.join(root, f_name)
                    rel_path = f"site/{os.path.relpath(file_path, extract_dir)}".replace("\\", "/")
                    f_obj = open(file_path, 'rb')
                    open_files.append(f_obj)
                    files.append(('file', (rel_path, f_obj)))
                    
            resp = await asyncio.to_thread(requests.post, url, headers=headers, files=files)
            
            if resp.status_code == 200:
                cid = resp.json().get("IpfsHash")
                
                await brain.add_vector_async(
                    post_id=int(time.time()),
                    hash_id=cid,
                    text=text_content[:2000],
                    item_type="website",
                    author="",
                    metadata=json.dumps({"title": title, "description": description})
                )
                return {"cid": cid, "title": title}
            else:
                raise HTTPException(status_code=500, detail=f"Pinata error: {resp.text}")
        finally:
            for f in open_files:
                f.close()

@app.post("/proxy/publish_feedo")
async def proxy_publish_feedo(file: UploadFile = File(...)):
    import tempfile
    import zipfile
    import shutil
    import requests
    from bs4 import BeautifulSoup
    
    storage_node_url = os.getenv("STORAGE_NODE_URL", "http://storage-node:3001")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "site.zip")
        with open(zip_path, "wb") as f:
            content = await file.read()
            f.write(content)
            
        extract_dir = os.path.join(tmpdir, "extracted")
        os.makedirs(extract_dir)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
            
        root_items = os.listdir(extract_dir)
        if len(root_items) == 1 and os.path.isdir(os.path.join(extract_dir, root_items[0])):
            extract_dir = os.path.join(extract_dir, root_items[0])
            
        title = "Unknown Site"
        description = ""
        text_content = ""
        index_path = os.path.join(extract_dir, "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                html_content = f.read()
                soup = BeautifulSoup(html_content, 'html.parser')
                if soup.title:
                    title = soup.title.string
                meta_desc = soup.find("meta", {"name": "description"})
                if meta_desc and meta_desc.get("content"):
                    description = meta_desc["content"]
                text_content = soup.get_text(separator=' ', strip=True)

        # Extract favicon: search for favicon.ico, favicon.png, icon.png, apple-touch-icon.png
        icon_cid = None
        favicon_names = ["favicon.ico", "favicon.png", "icon.png", "apple-touch-icon.png"]
        favicon_path = None
        for fn in favicon_names:
            candidate = os.path.join(extract_dir, fn)
            if os.path.exists(candidate):
                favicon_path = candidate
                break
        if favicon_path is None:
            # Search one level deeper if favicon is in a subdirectory
            for root, _, files_in_dir in os.walk(extract_dir):
                for fn in favicon_names:
                    if fn in files_in_dir:
                        favicon_path = os.path.join(root, fn)
                        break
                if favicon_path:
                    break

        if favicon_path:
            with open(favicon_path, 'rb') as icon_f:
                icon_files = {'file': (os.path.basename(favicon_path), icon_f, 'application/octet-stream')}
                try:
                    icon_resp = await asyncio.to_thread(requests.post, f"{storage_node_url}/upload", files=icon_files)
                    if icon_resp.status_code == 200:
                        icon_cid = icon_resp.text.strip()
                except Exception as e:
                    print(f"⚠️ Failed to upload favicon: {e}")

        url = f"{storage_node_url}/upload"
        
        with open(zip_path, 'rb') as f_obj:
            files = {'file': (file.filename or 'site.zip', f_obj, 'application/zip')}
            resp = await asyncio.to_thread(requests.post, url, files=files)
            
        if resp.status_code == 200:
            feedo_hash = resp.text.strip()
            
            metadata = {"title": title, "description": description}
            if icon_cid:
                metadata["icon_cid"] = icon_cid

            await brain.add_vector_async(
                post_id=int(time.time()),
                hash_id=feedo_hash,
                text=text_content[:2000],
                item_type="website",
                author="",
                metadata=json.dumps(metadata)
            )
            # Returning "cid" for compatibility with frontend code
            result = {"cid": feedo_hash, "title": title}
            if icon_cid:
                result["icon_cid"] = icon_cid
            return result
        else:
            raise HTTPException(status_code=500, detail=f"Storage node error: {resp.text}")

@app.post("/p2p/search")
async def p2p_search(payload: SearchPayload):
    result = await client_query(payload.query, limit=10, federated=payload.ttl > 1)
    return {"query": payload.query, "results": result["results"]}

@app.post("/p2p/index_vector")
async def p2p_index_vector(payload: IndexVectorPayload):
    """Receive a pre-computed vector from a peer node and index it locally.
    This is the write-side of semantic sharding: when a crawler determines
    a vector does not belong to its shard, it forwards it here.
    No shard check is performed — we trust the sender."""
    try:
        brain.add_vector_by_emb(
            post_id=payload.post_id,
            hash_id=payload.hash_id,
            vector=payload.vector,
            source_type=payload.source_type,
            item_type=payload.item_type,
            author=payload.author,
            text=payload.text,
            metadata=payload.metadata,
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/proxy/unpin/{cid}")
async def proxy_unpin(cid: str):
    pinata_api_key = os.getenv("PINATA_API_KEY")
    pinata_secret = os.getenv("PINATA_SECRET_API_KEY")
    
    if not pinata_api_key or not pinata_secret:
        raise HTTPException(status_code=500, detail="Pinata API keys not configured on server")
        
    url = f"https://api.pinata.cloud/pinning/unpin/{cid}"
    headers = {
        "pinata_api_key": pinata_api_key,
        "pinata_secret_api_key": pinata_secret
    }
    
    import requests
    resp = await asyncio.to_thread(requests.delete, url, headers=headers)
    
    # Remove from VectorBrain
    await brain.delete_vector_async(cid)
    
    if resp.status_code == 200:
        return {"status": "ok", "message": f"Unpinned {cid}"}
    elif resp.status_code == 404:
        return {"status": "ok", "message": f"CID {cid} not found on Pinata, but removed from VectorBrain"}
    else:
        raise HTTPException(status_code=500, detail=f"Pinata error: {resp.text}")

@app.delete("/proxy/unpin_feedo/{cid}")
async def proxy_unpin_feedo(cid: str):
    import requests
    storage_node_url = os.getenv("STORAGE_NODE_URL", "http://storage-node:3001")
    url = f"{storage_node_url}/delete/{cid}"
    
    try:
        resp = await asyncio.to_thread(requests.delete, url)
        await brain.delete_vector_async(cid)
        
        if resp.status_code == 200:
            return {"status": "ok", "message": f"Deleted {cid} from storage and search index"}
        else:
            return {"status": "partial", "message": f"Storage returned {resp.status_code}, but removed from search index"}
    except Exception as e:
        await brain.delete_vector_async(cid)
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
