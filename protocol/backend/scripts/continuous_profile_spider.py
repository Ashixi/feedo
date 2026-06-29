import asyncio
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
        self.max_concurrent_relays = max_concurrent_relays
        self.processed_pubkeys = set()
        self.db_queue = asyncio.Queue()
        
        for r in SEED_RELAYS:
            self.add_relay(r)

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
                        pubkeys = [ev["pubkey"] for ev in batch]
                        stmt = select(Post.author_address).where(
                            Post.author_address.in_(pubkeys),
                            Post.item_type == "profile"
                        )
                        existing = set((await session.execute(stmt)).scalars().all())
                        
                        count = 0
                        for ev in batch:
                            if ev["pubkey"] in existing:
                                continue
                            
                            try:
                                content = json.loads(ev["content"])
                            except Exception:
                                content = {}
                                
                            new_post = Post(
                                source_type="nostr",
                                source_specific_id=ev["id"],
                                hash_id=ev["id"],
                                author_address=ev["pubkey"],
                                text_content=ev["content"],
                                metadata_=content,
                                item_type="profile",
                                content_type=ContentType.TEXT
                            )
                            session.add(new_post)
                            existing.add(ev["pubkey"])
                            count += 1
                            
                        if count > 0:
                            await session.commit()
                            logger.info(f"💾 Saved {count} new profiles to DB. Total known: {len(self.known_relays)} relays.")
                            
            except Exception as e:
                logger.error(f"DB Writer error: {e}")
                await asyncio.sleep(1)

    async def crawl_relay(self, relay_url: str):
        self.active_relays.add(relay_url)
        logger.info(f"🕷️ Connecting to {relay_url} ...")
        req_id = f"spider_{os.urandom(4).hex()}"
        
        try:
            async with websockets.connect(relay_url, open_timeout=5.0, close_timeout=1.0) as ws:
                req_msg = json.dumps(["REQ", req_id, {"kinds": [0, 10002]}])
                await ws.send(req_msg)
                
                start_time = asyncio.get_running_loop().time()
                while asyncio.get_running_loop().time() - start_time < 300: 
                    try:
                        msg_str = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        msg = json.loads(msg_str)
                        
                        if msg[0] == "EOSE" and msg[1] == req_id:
                            logger.info(f"🏁 EOSE from {relay_url}")
                            break
                            
                        if msg[0] == "EVENT" and msg[1] == req_id:
                            ev = msg[2]
                            kind = ev.get("kind")
                            
                            if kind == 10002:
                                for tag in ev.get("tags", []):
                                    if tag and tag[0] == "r" and len(tag) > 1:
                                        self.add_relay(tag[1])
                                        
                            elif kind == 0:
                                pubkey = ev.get("pubkey")
                                if pubkey and pubkey not in self.processed_pubkeys:
                                    self.db_queue.put_nowait(ev)
                                    self.processed_pubkeys.add(pubkey)
                                    
                    except asyncio.TimeoutError:
                        break
                    except json.JSONDecodeError:
                        continue
                        
                try:
                    await ws.send(json.dumps(["CLOSE", req_id]))
                except:
                    pass
                    
        except Exception as e:
            logger.debug(f"⚠️ Disconnected from {relay_url}: {e}")
            
        finally:
            self.active_relays.remove(relay_url)

    async def run(self):
        logger.info("Loading existing profiles from DB...")
        async with AsyncSessionLocal() as session:
            stmt = select(Post.author_address).where(Post.item_type == "profile")
            result = await session.execute(stmt)
            self.processed_pubkeys = set(row[0] for row in result.all() if row[0])
            logger.info(f"Loaded {len(self.processed_pubkeys)} pubkeys.")

        asyncio.create_task(self.db_writer_loop())
        
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
