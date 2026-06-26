import os
import time
import asyncio
import httpx
import logging
import json
import hashlib
import nacl.signing
import nacl.exceptions
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("feedo-tracker")

app = FastAPI(title="Feedo Tracker (Spider)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BOOTSTRAP_NODES = os.environ.get("BOOTSTRAP_NODES", "http://localhost:8000").split(",")
ACTIVE_NODES = []

def verify_signature(hash_id: str, signature_hex: str, wallet_address_hex: str) -> bool:
    try:
        vk_bytes = bytes.fromhex(wallet_address_hex.replace("0x", ""))
        verify_key = nacl.signing.VerifyKey(vk_bytes)
        signature_bytes = bytes.fromhex(signature_hex.replace("0x", ""))
        digest = bytes.fromhex(hash_id)
        verify_key.verify(digest, signature_bytes)
        return True
    except Exception:
        return False

OFFICIAL_TREASURY_URL = os.environ.get("OFFICIAL_TREASURY_URL", "https://api.feedo.ink").rstrip("/")

async def verify_node_health(url: str) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/api/v1/health", timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                node_treasury = data.get("treasury_url", "").rstrip("/")
                if node_treasury == "local" or node_treasury == OFFICIAL_TREASURY_URL:
                    return True
                else:
                    logger.warning(f"Node {url} rejected: treasury_url is {node_treasury}, expected {OFFICIAL_TREASURY_URL}")
            return False
    except Exception:
        return False

async def crawl_network():
    global ACTIVE_NODES
    while True:
        try:
            logger.info("Spider starting crawl...")
            visited_urls = set()
            valid_nodes = []
            queue = [node.strip() for node in BOOTSTRAP_NODES if node.strip()]
            
            async with httpx.AsyncClient() as client:
                while queue:
                    current_url = queue.pop(0)
                    if current_url in visited_urls:
                        continue
                    visited_urls.add(current_url)
                    
                    try:
                        logger.info(f"Crawling {current_url}")
                        resp = await client.get(f"{current_url}/api/v1/network/peers", timeout=5.0)
                        if resp.status_code == 200:
                            peers = resp.json()
                            for peer in peers:
                                pubkey = peer.get("pubkey")
                                api_url = peer.get("api_url")
                                timestamp = peer.get("timestamp", 0)
                                sig = peer.get("sig")
                                
                                # Protect against replay / stale nodes (older than 10 minutes)
                                if time.time() - timestamp > 600:
                                    continue
                                    
                                # Verify signature
                                data_str = f"{pubkey}_{api_url}_{timestamp}"
                                hash_id = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
                                if not verify_signature(hash_id, sig, pubkey):
                                    continue
                                    
                                if api_url not in visited_urls and api_url not in queue:
                                    queue.append(api_url)
                                    
                                # Check health
                                if api_url not in [n["api_url"] for n in valid_nodes]:
                                    if await verify_node_health(api_url):
                                        valid_nodes.append({
                                            "pubkey": pubkey,
                                            "api_url": api_url
                                        })
                    except Exception as e:
                        logger.warning(f"Failed to crawl {current_url}: {e}")
            
            ACTIVE_NODES = valid_nodes
            logger.info(f"Crawl finished. Found {len(ACTIVE_NODES)} active public nodes.")
            
        except Exception as e:
            logger.error(f"Crawl error: {e}")
            
        # Wait 30 seconds before next crawl
        await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(crawl_network())

@app.get("/nodes")
async def get_nodes():
    return ACTIVE_NODES

@app.get("/health")
async def health():
    return {"status": "ok", "nodes_count": len(ACTIVE_NODES)}
