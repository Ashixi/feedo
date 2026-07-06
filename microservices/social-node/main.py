import asyncio
import os
import uvicorn
from fastapi import FastAPI, Request
from pydantic import BaseModel
import aiohttp
import json
import sqlite3
import time

app = FastAPI(title="Social Node")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_DIR = os.getenv("DB_PATH", "./social_data")
SQLITE_DB_PATH = os.path.join(DB_DIR, "profiles.db")

SEARCH_NODE_URL = os.getenv("SEARCH_NODE_URL", "http://127.0.0.1:8000")
STORAGE_NODE_URLS = os.getenv("GATEWAYS", "http://127.0.0.1:8040").split(",")

def init_sqlite():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS profiles (
            pubkey TEXT PRIMARY KEY,
            p2p_hash TEXT NOT NULL,
            nostr_created_at INTEGER NOT NULL,
            profile_json TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_sqlite()

async def get_profiles_batch(pubkeys: set) -> dict:
    if not pubkeys: return {}
    profiles = {}
    try:
        def fetch_sqlite():
            conn = sqlite3.connect(SQLITE_DB_PATH)
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(pubkeys))
            cursor.execute(f"SELECT pubkey, profile_json FROM profiles WHERE pubkey IN ({placeholders})", list(pubkeys))
            rows = cursor.fetchall()
            conn.close()
            return rows
            
        rows = await asyncio.to_thread(fetch_sqlite)
        for row in rows:
            pk, profile_json = row
            if profile_json:
                try: profiles[pk] = json.loads(profile_json)
                except: pass
        return profiles
    except Exception as e: 
        print("get_profiles_batch error:", e)
        return profiles

@app.get("/v1/identity/{pubkey}")
async def get_identity(pubkey: str):
    profiles = await get_profiles_batch({pubkey})
    return {"profile": profiles.get(pubkey, {})}

class SyncProfilePayload(BaseModel):
    pubkey: str
    p2p_hash: str
    nostr_created_at: int
    profile_json: str

@app.post("/v1/profiles/sync")
async def sync_profiles(payload: list[SyncProfilePayload]):
    try:
        def do_sync():
            conn = sqlite3.connect(SQLITE_DB_PATH)
            cursor = conn.cursor()
            for p in payload:
                cursor.execute('''
                    INSERT INTO profiles (pubkey, p2p_hash, nostr_created_at, profile_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(pubkey) DO UPDATE SET
                        p2p_hash=excluded.p2p_hash,
                        nostr_created_at=excluded.nostr_created_at,
                        profile_json=excluded.profile_json
                    WHERE excluded.nostr_created_at > profiles.nostr_created_at
                ''', (p.pubkey, p.p2p_hash, p.nostr_created_at, p.profile_json))
            conn.commit()
            conn.close()
        await asyncio.to_thread(do_sync)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}

@app.put("/v1/identity/update/{pubkey}")
async def update_identity(pubkey: str, payload: Request):
    try:
        data = await payload.json()
        meta = data.get("metadata", {})
        
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
            "ttl_days": 30
        }
        
        async with aiohttp.ClientSession() as session:
            for gateway in STORAGE_NODE_URLS:
                gateway = gateway.strip()
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

@app.get("/feed")
async def get_feed(limit: int = 50, offset: int = 0):
    """Fetches documents from search-node and decorates with profiles."""
    try:
        async with aiohttp.ClientSession() as session:
            search_url = f"{SEARCH_NODE_URL}/documents?limit={limit}&offset={offset}&item_type=social_post"
            async with session.get(search_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    records = data.get("results", [])
                else:
                    return []
                    
        feed_candidates = []
        unique_pubkeys = set()
        
        for r in records:
            author_did = r.get("author", "")
            pubkey = author_did.replace("did:feedo:schnorr:", "") if author_did else ""
            if pubkey: unique_pubkeys.add(pubkey)
            r["extracted_pubkey"] = pubkey
            feed_candidates.append(r)
            
        profiles_cache = await get_profiles_batch(unique_pubkeys)
        
        feed = []
        for r in feed_candidates:
            pubkey = r.get("extracted_pubkey", "")
            profile = profiles_cache.get(pubkey, {})
            author_name = profile.get("name") or profile.get("display_name")
            author_avatar = profile.get("picture")
            
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try: meta = json.loads(meta)
                except: meta = {}
                
            post_data = {
                "hash_id": r.get("hash_id"),
                "item_type": r.get("item_type", "social_post"),
                "text": r.get("text", ""),
                "author": pubkey,
                "metadata": meta,
                "published_at": meta.get("nostr_created_at")
            }
            if author_name: post_data["author_name"] = author_name
            if author_avatar: post_data["author_avatar"] = author_avatar
            
            feed.append(post_data)
            
        return feed
    except Exception as e:
        print("Error fetching feed:", e)
        return []

@app.get("/profiles/check")
async def check_profile(pubkey: str):
    profiles = await get_profiles_batch({pubkey})
    return {"exists": bool(profiles.get(pubkey))}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8010))
    uvicorn.run(app, host="0.0.0.0", port=port)
