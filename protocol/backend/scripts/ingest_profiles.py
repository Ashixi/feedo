import asyncio
import json
import logging
import os
import sys
import websockets
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models import Post, ContentType

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/feedo")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://relay.nostr.band"
]

async def fetch_and_store_profiles():
    async with AsyncSessionLocal() as session:
        # Get existing profile pubkeys
        stmt = select(Post.author_address).where(Post.item_type == "profile")
        result = await session.execute(stmt)
        existing_pubkeys = set(row[0] for row in result.all() if row[0])

        logging.info(f"Loaded {len(existing_pubkeys)} existing profiles from DB.")

        for relay in RELAYS:
            logging.info(f"Connecting to {relay}...")
            try:
                async with websockets.connect(relay, ping_interval=None) as ws:
                    req_id = "profiles_fetch"
                    filter_req = {"kinds": [0], "limit": 1000}
                    await ws.send(json.dumps(["REQ", req_id, filter_req]))

                    count = 0
                    skipped = 0

                    while True:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            data = json.loads(msg)
                            
                            if data[0] == "EOSE" and data[1] == req_id:
                                logging.info(f"End of stored events from {relay}")
                                break
                                
                            if data[0] == "EVENT" and data[1] == req_id:
                                ev = data[2]
                                pubkey = ev["pubkey"]
                                
                                if pubkey in existing_pubkeys:
                                    skipped += 1
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
                                    content_type=ContentType.TEXT
                                )
                                session.add(new_post)
                                existing_pubkeys.add(pubkey)
                                count += 1
                                
                                if count % 100 == 0:
                                    await session.commit()
                                    logging.info(f"Committed {count} profiles...")
                                    
                        except asyncio.TimeoutError:
                            logging.info(f"Timeout waiting for events from {relay}")
                            break
                        
                    await session.commit()
                    logging.info(f"Saved {count} new profiles from {relay}. Skipped {skipped}.")
                    await ws.send(json.dumps(["CLOSE", req_id]))
                    
            except Exception as e:
                logging.error(f"Error with {relay}: {e}")

async def main():
    await fetch_and_store_profiles()

if __name__ == "__main__":
    asyncio.run(main())
