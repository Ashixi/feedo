import asyncio
import json
import logging
import os
import time
import asyncpg
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/feedo")
BACKFILL_DAYS = int(os.getenv("BACKFILL_DAYS", "30"))
RELAYS = ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net"]

async def init_db():
    return await asyncpg.connect(DATABASE_URL)

async def fetch_recent_pubkeys():
    target_since = int(time.time()) - (BACKFILL_DAYS * 86400)
    active_pubkeys = set()
    
    for relay in RELAYS:
        logging.info(f"Fetching active authors from {relay} (last {BACKFILL_DAYS} days)...")
        try:
            async with websockets.connect(relay, ping_interval=None) as ws:
                req_id = "fetch_authors"
                # We do a simple since query. Some relays limit to 1000, 
                # so we might not get all, but we get the most recently active.
                # To be thorough, we would paginate by 'until', but for simplicity we fetch the latest block.
                filter_req = {"kinds": [1], "since": target_since, "limit": 10000}
                await ws.send(json.dumps(["REQ", req_id, filter_req]))
                
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        data = json.loads(msg)
                        if data[0] == "EOSE" and data[1] == req_id:
                            break
                        if data[0] == "EVENT" and data[1] == req_id:
                            active_pubkeys.add(data[2]["pubkey"])
                    except asyncio.TimeoutError:
                        break
                await ws.send(json.dumps(["CLOSE", req_id]))
        except Exception as e:
            logging.error(f"Error fetching from {relay}: {e}")
            
    logging.info(f"Total unique active authors found: {len(active_pubkeys)}")
    return list(active_pubkeys)

async def store_profiles(conn, pubkeys):
    # Fetch existing
    rows = await conn.fetch("SELECT author_address FROM posts WHERE item_type = 'profile'")
    existing = set(row["author_address"] for row in rows if row["author_address"])
    
    to_fetch = [pk for pk in pubkeys if pk not in existing]
    logging.info(f"Out of {len(pubkeys)} active authors, {len(to_fetch)} profiles are missing in DB.")
    
    if not to_fetch:
        return
        
    # Batch request
    batch_size = 200
    for i in range(0, len(to_fetch), batch_size):
        batch = to_fetch[i:i+batch_size]
        for relay in RELAYS:
            logging.info(f"Fetching profiles batch {i//batch_size + 1} from {relay}...")
            profiles_found = []
            try:
                async with websockets.connect(relay, ping_interval=None) as ws:
                    req_id = f"fetch_profiles_{i}"
                    filter_req = {"kinds": [0], "authors": batch}
                    await ws.send(json.dumps(["REQ", req_id, filter_req]))
                    
                    while True:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            data = json.loads(msg)
                            if data[0] == "EOSE" and data[1] == req_id:
                                break
                            if data[0] == "EVENT" and data[1] == req_id:
                                profiles_found.append(data[2])
                        except asyncio.TimeoutError:
                            break
                    await ws.send(json.dumps(["CLOSE", req_id]))
            except Exception as e:
                logging.error(f"Error fetching profiles from {relay}: {e}")
            
            # Insert into DB
            for ev in profiles_found:
                try:
                    content = json.loads(ev["content"])
                except:
                    content = {}
                    
                # Ensure we don't insert duplicate by hash_id
                try:
                    await conn.execute('''
                        INSERT INTO posts 
                        (source_type, source_specific_id, hash_id, author_address, text_content, metadata_, item_type, content_type)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, 'TEXT')
                        ON CONFLICT (source_type, source_specific_id) DO NOTHING
                    ''', "nostr", ev["id"], ev["id"], ev["pubkey"], ev["content"], json.dumps(content), "profile")
                except Exception as e:
                    logging.error(f"DB insert error: {e}")
            
            logging.info(f"Inserted {len(profiles_found)} profiles from {relay}.")

async def main():
    conn = await init_db()
    logging.info("Connected to database.")
    
    try:
        active_pubkeys = await fetch_recent_pubkeys()
        if active_pubkeys:
            await store_profiles(conn, active_pubkeys)
    finally:
        await conn.close()
        logging.info("Backfill finished. Exiting.")

if __name__ == "__main__":
    asyncio.run(main())
