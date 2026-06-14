from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
import httpx
import os
from bs4 import BeautifulSoup
import json
import uuid
import time
from typing import List

router = APIRouter()
RUST_CORE_URL = os.getenv("RUST_CORE_URL", "http://127.0.0.1:8041/local/publish")
RUST_UPLOAD_URL = RUST_CORE_URL.replace("/local/publish", "/local/dht/upload")

@router.post("/publish")
async def publish_website(request: Request, files: List[UploadFile] = File(...)):
    """Publish a Web3 website by uploading HTML/CSS/JS files and extracting semantics."""
    brain = getattr(request.app.state, "brain", None)
    if not brain:
        raise HTTPException(status_code=503, detail="Vector Brain not available")

    assets = {}
    index_html_content = ""
    index_hash = ""
    
    # 1. Завантаження файлів
    for file in files:
        content = await file.read()
        if file.filename == "index.html":
            index_html_content = content.decode('utf-8', errors='ignore')
            
        async with httpx.AsyncClient() as client:
            files_dict = {'file': (file.filename, content, file.content_type)}
            try:
                res = await client.post(RUST_UPLOAD_URL, files=files_dict, timeout=10.0)
                if res.status_code == 200:
                    file_hash = res.text.strip()
                    assets[file.filename] = file_hash
                    if file.filename == "index.html":
                        index_hash = file_hash
                else:
                    raise HTTPException(status_code=500, detail=f"Failed to upload {file.filename}: {res.text}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Rust DHT upload failed: {e}")
                
    if not index_html_content:
        raise HTTPException(status_code=400, detail="index.html is required")

    # 2. Екстракція тексту
    soup = BeautifulSoup(index_html_content, "html.parser")
    title = soup.title.string if soup.title else ""
    meta_desc = ""
    desc_tag = soup.find("meta", attrs={"name": "description"})
    if desc_tag:
        meta_desc = desc_tag.get("content", "")
        
    body_text = soup.body.get_text(separator=' ', strip=True) if soup.body else ""
    full_text = f"{title}. {meta_desc}. {body_text}"

    # 3. Векторизація
    post_hash = f"website_{uuid.uuid4().hex}"
    author = "anonymous" 
    
    metadata = {
        "feedo_type": "website",
        "index": index_hash,
        "assets": assets
    }
    
    # 4. Публікація FeedoBroadcast
    broadcast_req = {
        "text": full_text[:5000],
        "author": author,
        "signature": "dummy_signature",
        "hash_id": post_hash,
        "content_blob_hash": index_hash,
        "title": title or "Web3 Site",
        "source_type": "website",
        "sequence_number": 1,
        "timestamp": int(time.time()),
        "metadata_": metadata
    }
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(RUST_CORE_URL, json=broadcast_req, timeout=10.0)
        except Exception as e:
            print(f"Warning: Failed to broadcast website to rust core: {e}")
            
    # Add to vector brain manually so semantic search works
    try:
        vector = await brain.get_embedding_async(full_text)
        brain.add_vector_by_emb(
            post_id=0,
            hash_id=post_hash,
            vector=vector,
            source_type="website"
        )
    except Exception as e:
        print(f"Vectorization failed: {e}")

    return {
        "status": "success",
        "hash_id": post_hash,
        "metadata": metadata
    }
