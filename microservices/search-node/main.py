import asyncio
import os
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
import zipfile
import tempfile
import shutil
from bs4 import BeautifulSoup
from pydantic import BaseModel
import aiohttp
import json

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

@app.on_event("startup")
async def startup_event():
    global p2p_net, crawler
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "127.0.0.1")
    
    p2p_net = P2PNetwork(brain, host, port)
    asyncio.create_task(p2p_net.broadcast_centroids_loop())
    
    adapters = [FeedoStorageAdapter(), IPFSStorageAdapter()]
    crawler = SearchCrawler(brain, adapters)
    asyncio.create_task(crawler.crawl_loop())

@app.post("/p2p/handshake")
async def p2p_handshake(payload: HandshakePayload):
    brain.update_global_map(payload.peer_id, payload.centroids, payload.cluster_ids)
    if p2p_net and payload.peer_id:
        p2p_net.known_peers.add(payload.peer_id)
    return {"status": "ok"}

@app.get("/query")
async def client_query(text: str, limit: int = 50, federated: bool = True, item_type: str = "all", offset: int = 0):
    query_vector = await brain.get_embedding_async(text, is_query=True)
    local_results = []
    
    try:
        fetch_limit = (limit + offset) * 5
        def search_lance_vector(qv, flimit):
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
        federated_results = await p2p_net.federated_search(query_vector, text, ttl=3, top_k=5)
    
    all_results = local_results + federated_results
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    seen = set()
    final_results = []
    for r in all_results:
        if r["hash_id"] not in seen:
            if item_type == "all" or item_type == r["item_type"]:
                seen.add(r["hash_id"])
                final_results.append(r)
            if len(final_results) >= limit + offset:
                break
                
    final_results = final_results[offset:]
    await fetch_missing_text_from_dht(final_results)
            
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
                
        url = f"{storage_node_url}/upload"
        
        with open(zip_path, 'rb') as f_obj:
            files = {'file': (file.filename or 'site.zip', f_obj, 'application/zip')}
            resp = await asyncio.to_thread(requests.post, url, files=files)
            
        if resp.status_code == 200:
            feedo_hash = resp.text.strip()
            
            await brain.add_vector_async(
                post_id=int(time.time()),
                hash_id=feedo_hash,
                text=text_content[:2000],
                item_type="website",
                author="",
                metadata=json.dumps({"title": title, "description": description})
            )
            # Returning "cid" for compatibility with frontend code
            return {"cid": feedo_hash, "title": title}
        else:
            raise HTTPException(status_code=500, detail=f"Storage node error: {resp.text}")

@app.post("/p2p/search")
async def p2p_search(payload: SearchPayload):
    result = await client_query(payload.query, limit=10, federated=payload.ttl > 1)
    return {"query": payload.query, "results": result["results"]}

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

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
