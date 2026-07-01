import asyncio
import aiohttp
import json
import logging
import os
import sys
import websockets
from urllib.parse import urlparse
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

# Setup Python Path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models import Post, ContentType

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("profile_spider")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/feedo")
engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

SEED_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://relay.nostr.band",
    "wss://purplepag.es",
    "wss://user.kind0.me",
    "wss://relay.snort.social"
]

class ProfileSpider:
    def __init__(self, max_concurrent_relays=15):
        self.relay_queue = asyncio.Queue()
        self.known_relays = set()
        self.active_relays = set()
        self.assigned_relays = set()
        self.max_concurrent_relays = max_concurrent_relays
        self.processed_pubkeys = set()
        self.db_queue = asyncio.Queue()
        
        self.node_rank = 0
        self.total_nodes = 1

    def add_relay(self, url: str):
        try:
            parsed = urlparse(url)
            if parsed.scheme in ("ws", "wss") and parsed.netloc:
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if clean_url not in self.known_relays:
                    self.known_relays.add(clean_url)
                    self.relay_queue.put_nowait(clean_url)
        except Exception:
            pass

    async def network_sync_loop(self):
        logger.info("Network Sync loop started")
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get("http://feedo-p2p:4001/local/network_info", timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data:
                                self.node_rank = data.get("node_rank", 0)
                                self.total_nodes = data.get("total_nodes", 1)
            except Exception as e:
                logger.debug(f"P2P Network Info not available, defaulting to standalone mode. Error: {e}")
                self.node_rank = 0
                self.total_nodes = 1

            # Load global list of relays from DB to ensure all nodes sort the same list
            global_relays = set(SEED_RELAYS)
            try:
                async with AsyncSessionLocal() as session:
                    res = await session.execute(select(Post.relay_urls).where(Post.item_type == "profile").limit(1)) # Just to check db connection
                    # Actually we should query discovered_relays, but we don't have the model here.
                    # We can use raw SQL:
                    from sqlalchemy import text
                    res = await session.execute(text("SELECT url FROM discovered_relays"))
                    for row in res.fetchall():
                        if row[0].startswith("ws"):
                            global_relays.add(row[0])
            except Exception as e:
                logger.debug(f"Failed to load global relays from DB: {e}")
                
            global_relays.update(self.known_relays)
            sorted_relays = sorted(global_relays)

            new_assigned = set()
            for i, r in enumerate(sorted_relays):
                if i % self.total_nodes == self.node_rank:
                    new_assigned.add(r)
            
            # Find newly assigned
            for r in new_assigned:
                if r not in self.assigned_relays:
                    logger.info(f"Assigned new relay: {r} (Rank {self.node_rank}/{self.total_nodes})")
                    self.assigned_relays.add(r)
                    self.add_relay(r)
                    
            # Find revoked relays
            for r in list(self.assigned_relays):
                if r not in new_assigned:
                    logger.info(f"Revoked relay: {r}")
                    self.assigned_relays.remove(r)
                    if r in self.known_relays:
                        self.known_relays.remove(r)

            await asyncio.sleep(30)

    async def db_writer_loop(self):
        """Batch writes new profiles to the database."""
        logger.info("DB Writer started")
        while True:
            batch = []
            try:
                item = await self.db_queue.get()
                batch.append(item)
                
                while len(batch) < 100:
                    try:
                        item = self.db_queue.get_nowait()
                        batch.append(item)
                    except asyncio.QueueEmpty:
                        break
                        
                if batch:
                    async with AsyncSessionLocal() as session:
                        pubkeys = [ev["pubkey"] for ev, _ in batch]
                        stmt = select(Post).where(
                            Post.author_address.in_(pubkeys),
                            Post.item_type == "profile"
                        )
                        existing_posts = (await session.execute(stmt)).scalars().all()
                        existing_map = {p.author_address: p for p in existing_posts}
                        
                        count_new = 0
                        count_updated = 0
                        
                        for ev, relay_url in batch:
                            pubkey = ev["pubkey"]
                            if pubkey in existing_map:
                                post = existing_map[pubkey]
                                current_relays = post.relay_urls or []
                                if relay_url not in current_relays:
                                    # Create a new list for SQLAlchemy to detect JSON change
                                    new_relays = list(current_relays)
                                    new_relays.append(relay_url)
                                    post.relay_urls = new_relays
                                    count_updated += 1
                                continue
                            
                            try:
                                content = json.loads(ev["content"])
                            except Exception:
                                content = {}
                                
                            new_post = Post(
                                source_type="nostr",
                                source_specific_id=ev["id"],
                                hash_id=ev["id"],
                                author_address=pubkey,
                                text_content=ev["content"],
                                metadata_=content,
                                item_type="profile",
                                content_type=ContentType.TEXT,
                                relay_urls=[relay_url]
                            )
                            session.add(new_post)
                            existing_map[pubkey] = new_post # Prevent duplicates in same batch
                            count_new += 1
                            
                        if count_new > 0 or count_updated > 0:
                            await session.commit()
                            logger.info(f"💾 Saved {count_new} new profiles, updated {count_updated} with new relays. Total known: {len(self.known_relays)} relays.")
                            
            except Exception as e:
                logger.error(f"DB Writer error: {e}")
                await asyncio.sleep(1)

    async def crawl_relay(self, relay_url: str):
        self.active_relays.add(relay_url)
        logger.info(f"🕷️ Connecting to {relay_url} ...")
        
        # We need two subscriptions:
        # 1. Real-time updates (since current time)
        # 2. Backfill (paginating backwards)
        current_time = int(datetime.utcnow().timestamp())
        six_months_sec = 180 * 24 * 60 * 60
        stop_ts = current_time - six_months_sec
        until_ts = current_time
        
        req_id_rt = f"rt_{os.urandom(4).hex()}"
        req_id_bf = f"bf_{os.urandom(4).hex()}"
        
        backfill_done = False
        min_created_at = current_time
        events_in_batch = 0
        
        try:
            async with websockets.connect(relay_url, open_timeout=5.0, close_timeout=1.0) as ws:
                # 1. Start real-time subscription
                rt_msg = json.dumps(["REQ", req_id_rt, {"kinds": [0, 10002], "since": current_time}])
                await ws.send(rt_msg)
                
                # 2. Start initial backfill subscription
                bf_msg = json.dumps(["REQ", req_id_bf, {"kinds": [0, 10002], "limit": 1000, "until": until_ts}])
                await ws.send(bf_msg)
                
                while True:
                    if relay_url not in self.assigned_relays:
                        logger.info(f"Relay {relay_url} reassigned to another node. Disconnecting.")
                        return
                        
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=10.0)
                        msg = json.loads(message)
                        
                        if msg[0] == "EOSE":
                            if msg[1] == req_id_bf:
                                # Backfill batch finished
                                try:
                                    await ws.send(json.dumps(["CLOSE", req_id_bf]))
                                except: pass
                                
                                # Decide if we should continue backfilling
                                if events_in_batch == 0 or min_created_at <= stop_ts:
                                    if not backfill_done:
                                        logger.info(f"🏁 Backfill complete for {relay_url} (reached stop time or empty).")
                                        backfill_done = True
                                else:
                                    # Send next backfill batch
                                    until_ts = min_created_at
                                    req_id_bf = f"bf_{os.urandom(4).hex()}"
                                    bf_msg = json.dumps(["REQ", req_id_bf, {"kinds": [0, 10002], "limit": 1000, "until": until_ts}])
                                    await ws.send(bf_msg)
                                    events_in_batch = 0
                                    
                        elif msg[0] == "EVENT":
                            req_id_recv = msg[1]
                            ev = msg[2]
                            kind = ev.get("kind")
                            ev_created_at = ev.get("created_at", current_time)
                            
                            if req_id_recv == req_id_bf:
                                events_in_batch += 1
                                min_created_at = min(min_created_at, ev_created_at)
                            
                            if kind == 10002:
                                for tag in ev.get("tags", []):
                                    if tag and tag[0] == "r" and len(tag) > 1:
                                        self.add_relay(tag[1])
                                        
                            elif kind == 0:
                                pubkey = ev.get("pubkey")
                                if pubkey:
                                    cache_key = f"{pubkey}:{relay_url}:{ev_created_at}"
                                    if cache_key not in self.processed_pubkeys:
                                        self.db_queue.put_nowait((ev, relay_url))
                                        self.processed_pubkeys.add(cache_key)
                                    
                    except asyncio.TimeoutError:
                        continue
                    except json.JSONDecodeError:
                        continue
                        
                try:
                    await ws.send(json.dumps(["CLOSE", req_id_rt]))
                    if not backfill_done:
                        await ws.send(json.dumps(["CLOSE", req_id_bf]))
                except:
                    pass
                    
        except Exception as e:
            logger.debug(f"⚠️ Disconnected from {relay_url}: {e}")
            
        finally:
            self.active_relays.remove(relay_url)
            
            # Re-queue the relay after a short delay so it truly runs continuously
            if relay_url in self.assigned_relays:
                asyncio.create_task(self._requeue_relay(relay_url))

    async def _requeue_relay(self, relay_url: str):
        await asyncio.sleep(60)
        if relay_url in self.assigned_relays:
            self.relay_queue.put_nowait(relay_url)

    async def run(self):
        logger.info("Loading existing profiles from DB...")
        async with AsyncSessionLocal() as session:
            stmt = select(Post.author_address).where(Post.item_type == "profile")
            result = await session.execute(stmt)
            self.processed_pubkeys = set(row[0] for row in result.all() if row[0])
            logger.info(f"Loaded {len(self.processed_pubkeys)} pubkeys.")

        asyncio.create_task(self.db_writer_loop())
        asyncio.create_task(self.network_sync_loop())
        
        async def worker():
            while True:
                relay = await self.relay_queue.get()
                await self.crawl_relay(relay)
                self.relay_queue.task_done()
                await asyncio.sleep(1) 
                
        workers = [asyncio.create_task(worker()) for _ in range(self.max_concurrent_relays)]
        await asyncio.gather(*workers)

if __name__ == "__main__":
    spider = ProfileSpider(max_concurrent_relays=15)
    asyncio.run(spider.run())
