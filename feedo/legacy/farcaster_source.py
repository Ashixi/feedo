import json
import os
import logging
import asyncio
from datetime import datetime, timezone

import httpx

from .base import BaseSource
from .text_utils import clean_plain_text, chunk_long_text

logger = logging.getLogger("farcaster_source")

FARCASTER_HUB_URL = "https://nemes.farcaster.xyz:2281"
FARCASTER_EPOCH = 1609459200
STATE_FILE = "/app/db/farcaster_state.json"
MAX_FID = 800000

class FarcasterSource(BaseSource):
    source_type = "farcaster"
    
    def __init__(self):
        super().__init__()
        self.seen_hashes = set()
        self.current_fid = self._load_state()

    def _load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    return json.load(f).get("current_fid", 1)
            except Exception as e:
                logger.error(f"Error loading farcaster state: {e}")
        return 1
        
    def _save_state(self, fid: int):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump({"current_fid": fid, "updated_at": datetime.utcnow().isoformat()}, f)
        except Exception as e:
            logger.error(f"Error saving farcaster state: {e}")

    async def fetch_new(self, since: datetime | None) -> list[dict]:
        return []

    async def fetch_new_batches(self, since: datetime | None, node_index: int = 0, total_nodes: int = 1, db=None):
        logger.info(f"🕸️ SPIDER: Farcaster start fetching from FID {self.current_fid}")
        
        async with httpx.AsyncClient() as client:
            # We process a chunk of 50 FIDs per unified_monitor tick to allow DB commits and UI updates
            for _ in range(50):
                if self.current_fid >= MAX_FID:
                    logger.info(f"Reached MAX_FID {MAX_FID}. Resetting to 1 to find new users...")
                    self.current_fid = 1
                    self._save_state(self.current_fid)
                    await asyncio.sleep(3600)
                    return
                
                fid = self.current_fid
                self.current_fid += 1
                self._save_state(self.current_fid)
                
                if total_nodes > 1 and fid % total_nodes != node_index:
                    continue
                    
                batch_posts = []
                url = f"{FARCASTER_HUB_URL}/v1/castsByFid?fid={fid}&pageSize=100"
                
                data = None
                for _ in range(3):
                    try:
                        res = await client.get(url, timeout=10.0)
                        if res.status_code != 200:
                            if res.status_code == 429:
                                logger.warning(f"Rate limited by Farcaster Hub for FID {fid}. Sleeping 10s...")
                                await asyncio.sleep(10)
                                continue
                            else:
                                break
                        data = res.json()
                        break
                    except Exception as e:
                        logger.debug(f"Error querying Farcaster Hub for FID {fid}: {e}")
                        await asyncio.sleep(2)
                        
                if not data:
                    continue
                    
                messages = data.get("messages", [])
                if not messages:
                    continue
                    
                for msg in messages:
                    msg_data = msg.get("data", {})
                    if msg_data.get("type") != "MESSAGE_TYPE_CAST_ADD":
                        continue
                        
                    msg_hash = msg.get("hash")
                    if msg_hash in self.seen_hashes:
                        continue
                    self.seen_hashes.add(msg_hash)
                    
                    fc_timestamp = msg_data.get("timestamp", 0)
                    real_unix_ts = fc_timestamp + FARCASTER_EPOCH
                    pub_date = datetime.fromtimestamp(real_unix_ts, tz=timezone.utc).replace(tzinfo=None)
                    
                    body = msg_data.get("castAddBody", {})
                    text = body.get("text", "")
                    
                    if not text.strip():
                        continue
                        
                    parent = body.get("parentCastId")
                    is_reply = bool(parent)
                    
                    cleaned_text = clean_plain_text(text)
                    chunks = chunk_long_text(cleaned_text, chunk_size=512, overlap=50)
                    
                    author_fid = msg_data.get("fid", fid)
                    
                    for i, chunk in enumerate(chunks):
                        if not chunk.strip():
                            continue
                            
                        batch_posts.append({
                            "source_specific_id": f"fc_{msg_hash}_chunk_{i}",
                            "text_content": chunk,
                            "author_address": str(author_fid),
                            "original_author_name": f"fid:{author_fid}",
                            "signature": msg.get("signature", msg_hash),
                            "hash_id": f"{msg_hash}_c{i}", 
                            "published_at": pub_date,
                            "relay_url": f"https://warpcast.com/~/conversations/{msg_hash}",
                            "item_type": "cast_chunk",
                            "metadata_": {
                                "fid": author_fid,
                                "hash": msg_hash,
                                "chunk_index": i,
                                "total_chunks": len(chunks),
                                "is_reply": is_reply
                            }
                        })
                        
                if batch_posts:
                    yield batch_posts
                    
                await asyncio.sleep(0.1)
