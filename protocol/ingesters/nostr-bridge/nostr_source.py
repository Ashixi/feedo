import os
import json
import uuid
import asyncio
import websockets
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Set
from coincurve import PublicKeyXOnly
import logging

from connection_pool import RelayConnectionPool
from nostr_kinds import extract_text_for_vectorization

logger = logging.getLogger("nostr_source")

def _calc_nostr_event_id(event: dict) -> str:
    canonical = [
        0, 
        event.get("pubkey", ""),
        event.get("created_at", 0),
        event.get("kind", 0),
        event.get("tags", []),
        event.get("content", ""),
    ]
    encoded = json.dumps(canonical, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def _verify_nostr_event_signature(event: dict) -> bool:
    ev_id = event.get("id", "")
    sig_hex = event.get("sig", "")
    pubkey_hex = event.get("pubkey", "")

    if (
        not isinstance(ev_id, str)
        or not isinstance(sig_hex, str)
        or not isinstance(pubkey_hex, str)
        or len(ev_id) != 64
        or len(sig_hex) != 128
        or len(pubkey_hex) != 64 
    ):
        return False

    if _calc_nostr_event_id(event) != ev_id:
        return False

    try:
        pubkey = PublicKeyXOnly(bytes.fromhex(pubkey_hex))
        return pubkey.verify(bytes.fromhex(sig_hex), bytes.fromhex(ev_id))
    except Exception:
        return False

class NostrSource:
    source_type = "nostr"
    SEED_RELAYS = [
        "wss://relay.damus.io", "wss://nos.lol", "wss://relay.snort.social",
        "wss://nostr.wine", "wss://relay.nostr.band", "wss://purplepag.es",
        "wss://nostr.fmt.wiz.biz", "wss://relay.current.fyi", "wss://nostr-pub.wellorder.net",
        "wss://relay.nostr.info", "wss://nostr.bitcoiner.social", "wss://relay.nostr.bg",
        "wss://nostr.oxtr.dev", "wss://nostr.mom", "wss://relay.nostr.com.au",
        "wss://nostr.inosta.cc", "wss://nostr.mutinywallet.com", "wss://relay.primal.net",
        "wss://nostr.zebedee.cloud", "wss://relay.stoner.com", "wss://relay.nostr.net",
        "wss://eden.nostr.land", "wss://relay.nostrati.com", "wss://nostr.orangepill.dev"
    ]
    
    def __init__(self):
        # Shared connection pool
        self.pool = RelayConnectionPool(max_connections=1000)
        self.seen_ids = set()
        # Supported kinds for semantic indexing
        self.supported_kinds = [
            0, 1, 3, 6, 7, 40, 41, 42, 1063, 1311, 1984, 9735, 9802, 
            10000, 10001, 10002, 30000, 30001, 30008, 30009, 30023, 
            30311, 31922, 31923, 31990, 34550
        ]

    async def _fetch_from_relay(self, relay_url: str, req: list, timeout: float = 3.0) -> List[dict]:
        """Generic method to fetch events from a specific relay."""
        ws = await self.pool.get_connection(relay_url)
        if not ws:
            return []
            
        events = []
        try:
            await ws.send(json.dumps(req))
            while True:
                try:
                    msg_str = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    msg = json.loads(msg_str)
                    
                    if msg[0] == "EOSE" and msg[1] == req[1]:
                        break
                        
                    if msg[0] == "EVENT" and msg[1] == req[1]:
                        events.append(msg[2])
                except asyncio.TimeoutError:
                    break
        except Exception as e:
            logger.debug(f"Error reading from {relay_url}: {e}")
        return events

    async def discover_active_users_and_relays(self, since_ts: int, until_ts: int = None, db=None) -> tuple[Dict[str, List[str]], int]:
        """
        NIP-65: Queries directory relays for Kind 10002 to find active users and their write relays.
        Returns: ({pubkey: [relay_urls]}, oldest_timestamp)
        """
        sub_id = f"dir_{uuid.uuid4().hex[:8]}"
        req_filter = {"kinds": [10002], "limit": 1000}
        if until_ts:
            req_filter["until"] = until_ts
        req = ["REQ", sub_id, req_filter]
        
        seed_urls = list(self.SEED_RELAYS)
        if db:
            query = text("SELECT url FROM discovered_relays ORDER BY success_count DESC, last_seen_at DESC LIMIT 50")
            result = await db.execute(query)
            db_relays = [row[0] for row in result.fetchall()]
            if len(db_relays) >= 10:
                seed_urls = db_relays
        
        user_relays = {}
        min_created_at = None
        logger.info(f"Outbox Bridge: Querying {len(seed_urls)} seed relays concurrently...")
        
        tasks = [self._fetch_from_relay(r, req, timeout=10.0) for r in seed_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful_relays = []
        failed_relays = []
        
        for r, events in zip(seed_urls, results):
            if isinstance(events, Exception) or events is None or not events:
                failed_relays.append(r)
                continue
                
            successful_relays.append(r)
            for ev in events:
                if not _verify_nostr_event_signature(ev):
                    continue
                pubkey = ev.get("pubkey")
                ev_time = ev.get("created_at")
                if ev_time:
                    if min_created_at is None or ev_time < min_created_at:
                        min_created_at = ev_time
                        
                write_relays = []
                for tag in ev.get("tags", []):
                    if len(tag) >= 2 and tag[0] == "r":
                        if len(tag) == 2 or tag[2] == "write":
                            write_relays.append(tag[1])
                if write_relays:
                    user_relays[pubkey] = write_relays
                    
        if db:
            for r in successful_relays:
                await db.execute(text("UPDATE discovered_relays SET success_count = success_count + 1, last_seen_at = now() WHERE url = :u"), {"u": r})
            for r in failed_relays:
                await db.execute(text("UPDATE discovered_relays SET fail_count = fail_count + 1 WHERE url = :u"), {"u": r})
            
            new_relays = set()
            for pubkey, write_relays in user_relays.items():
                for r in write_relays:
                    if r.startswith("ws"):
                        new_relays.add(r)
            
            if new_relays:
                for r in new_relays:
                    await db.execute(text("""
                        INSERT INTO discovered_relays (url, last_seen_at, success_count, fail_count) 
                        VALUES (:u, now(), 0, 0) ON CONFLICT (url) DO NOTHING
                    """), {"u": r})
            await db.commit()
            
            # Export healthy relays to a file
            try:
                export_query = text("""
                    SELECT url, success_count, fail_count, last_seen_at 
                    FROM discovered_relays 
                    WHERE success_count > fail_count AND success_count > 0 
                    ORDER BY success_count DESC
                """)
                healthy_res = await db.execute(export_query)
                healthy_relays = [
                    {
                        "url": row[0],
                        "success_count": row[1],
                        "fail_count": row[2],
                        "last_seen_at": str(row[3])
                    } for row in healthy_res.fetchall()
                ]
                with open("/app/db/healthy_relays.json", "w", encoding="utf-8") as f:
                    json.dump(healthy_relays, f, indent=4)
                logger.info(f"Exported {len(healthy_relays)} healthy relays to /app/db/healthy_relays.json")
            except Exception as e:
                logger.error(f"Failed to export healthy relays: {e}")
            
        return user_relays, min_created_at

    async def fetch_new(self, since: datetime | None) -> list[dict]:
        # Required by BaseSource, but we use fetch_new_batches for sharded parsing
        return []

    async def fetch_new_batches(self, since: datetime | None, node_index: int = 0, total_nodes: int = 1, db=None, override_since_ts: int = None, override_until_ts: int = None):
        # Відмовляємося від глобального since, бо ми щоразу знаходимо нових авторів.
        # Використовуємо "ковзне вікно" за останні 6 годин (6 * 3600 секунд).
        since_ts = override_since_ts if override_since_ts else int(datetime.utcnow().timestamp()) - (6 * 3600)
        
        user_relays_map, min_created_at = await self.discover_active_users_and_relays(since_ts, until_ts=override_until_ts, db=db)
        logger.info(f"Outbox Bridge: Discovered {len(user_relays_map)} active users.")
        
        # We attach min_created_at to the object so the backfill script can read it
        self.last_min_created_at = min_created_at
        
        # Invert the map to group pubkeys by relay to optimize connections
        relay_to_pubkeys = {}
        for pubkey, relays in user_relays_map.items():
            for r in relays:
                if r not in relay_to_pubkeys:
                    relay_to_pubkeys[r] = []
                relay_to_pubkeys[r].append(pubkey)
                
        # Get all relays and apply SHARDING!
        sorted_relays = sorted(relay_to_pubkeys.keys(), key=lambda r: len(relay_to_pubkeys[r]), reverse=True)
        my_relays = sorted_relays[node_index :: total_nodes]
        
        logger.info(f"Sharding: Node {node_index}/{total_nodes} taking {len(my_relays)} out of {len(sorted_relays)} global relays.")
        
        sub_id = f"feedo_{uuid.uuid4().hex[:8]}"
        batch_size = 5 # yield after processing 5 relays
        
        for i in range(0, len(my_relays), batch_size):
            relay_chunk = my_relays[i:i + batch_size]
            batch_posts = []
            
            fetch_tasks = []
            for relay in relay_chunk:
                pubkeys = relay_to_pubkeys.get(relay, [])
                req_filter = {"kinds": self.supported_kinds, "since": since_ts, "limit": 500}
                if pubkeys:
                    req_filter["authors"] = pubkeys[:500] # Limit to 500 pubkeys per req to avoid relay rejection
                req = ["REQ", sub_id, req_filter]
                logger.debug(f"Fetching from {relay} for {len(pubkeys)} users...")
                fetch_tasks.append(self._fetch_from_relay(relay, req, timeout=15.0))
                
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            
            for relay, result in zip(relay_chunk, results):
                if isinstance(result, Exception):
                    logger.debug(f"Error fetching from {relay}: {result}")
                    continue
                    
                events = result
                for event in events:
                    ev_id = event["id"]
                    if ev_id in self.seen_ids:
                        continue
                    self.seen_ids.add(ev_id)
                    
                    if not _verify_nostr_event_signature(event):
                        continue
                        
                    is_reply = any(tag[0] == "e" for tag in event.get("tags", []))
                    if is_reply:
                        continue
                    try:
                        pub_date = datetime.utcfromtimestamp(event["created_at"])
                    except (OSError, OverflowError, ValueError):
                        logger.warning(f"Invalid timestamp {event.get('created_at')} in event {ev_id}, using current time")
                        pub_date = datetime.utcnow()
                    
                    # Stateless Indexer Core Magic:
                    # We extract ONLY the text necessary for vectorization.
                    # In unified_monitor, this text_content will be dropped and ONLY the vector + relay_url will be saved!
                    text_for_vector = extract_text_for_vectorization(event)
                    
                    # Extract explicitly defined image URLs from tags (NIP-92 imeta or plain url/image tags)
                    explicit_image_url = None
                    for tag in event.get("tags", []):
                        if len(tag) >= 2:
                            if tag[0] in ("url", "image") and tag[1].startswith("http"):
                                explicit_image_url = tag[1]
                                break
                            if tag[0] == "imeta":
                                for imeta_prop in tag[1:]:
                                    if imeta_prop.startswith("url "):
                                        url_val = imeta_prop[4:].strip()
                                        if url_val.startswith("http"):
                                            explicit_image_url = url_val
                                            break
                                if explicit_image_url:
                                    break
                    
                    # Якщо немає тексту, але є фото — ми все одно хочемо векторизувати це фото!
                    if not text_for_vector.strip() and not explicit_image_url:
                        continue
                    item_type = "profile" if event.get("kind") == 0 else "post"
    
                    batch_posts.append({
                        "source_specific_id": ev_id,
                        "text_content": text_for_vector, # Will be dropped by monitor if relay_url exists
                        "author_address": event["pubkey"],
                        "original_author_name": f"Nostr:{event['pubkey'][:8]}",
                        "signature": event["sig"],
                        "hash_id": ev_id,
                        "published_at": pub_date,
                        "relay_url": relay, # THIS is crucial for Stateless Indexer
                        "image_url": explicit_image_url, # Pass explicit image URL to unified_monitor
                        "item_type": item_type,
                        "metadata_": {
                            "is_reply": is_reply,
                            "tags": event.get("tags", []),
                            "kind": event.get("kind")
                        }
                    })
                    
            if batch_posts:
                yield batch_posts

import asyncio
import httpx

async def run_bridge():
    source = NostrSource()
    print("Starting Nostr Bridge...")
    
    INGEST_URL = os.getenv("INGEST_URL", "http://127.0.0.1:8040/api/v1/ingest/post")
    INGEST_API_KEY = os.getenv("INGEST_API_KEY", "feedo_default_ingest_key_2026")
    
    async with httpx.AsyncClient() as client:
        while True:
            try:
                async for batch in source.fetch_new_batches(since=None):
                    for post in batch:
                        payload = {
                            "text_content": post.get("text_content", ""),
                            "author_address": post.get("author_address", ""),
                            "source_type": "nostr",
                            "source_specific_id": post.get("source_specific_id", ""),
                            "published_at": post.get("published_at").isoformat() if post.get("published_at") else None,
                            "external_link": post.get("relay_url", ""),
                            "image_url": post.get("image_url", ""),
                            "metadata_": post.get("metadata_", {})
                        }
                        
                        try:
                            resp = await client.post(
                                INGEST_URL,
                                json=payload,
                                headers={"X-Ingest-Key": INGEST_API_KEY},
                                timeout=5.0
                            )
                            if resp.status_code != 201:
                                print(f"Failed to ingest post {post.get('source_specific_id')}: {resp.status_code} {resp.text}")
                        except Exception as e:
                            print(f"Error connecting to Ingest API: {e}")
                
                print("Cycle completed. Waiting 60 seconds...")
                await asyncio.sleep(60)
            except Exception as e:
                print(f"Error during fetch cycle: {e}")
                await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(run_bridge())
