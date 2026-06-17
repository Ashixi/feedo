import os
import asyncio
import logging
from datetime import datetime, timezone
import argparse

import unified_monitor

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill")

CURSOR_FILE = "/app/db/backfill_cursor.txt"

def load_cursor():
    if os.path.exists(CURSOR_FILE):
        try:
            with open(CURSOR_FILE, "r") as f:
                return int(f.read().strip())
        except Exception as e:
            logger.error(f"Error reading cursor file: {e}")
    return None

def save_cursor(ts: int):
    try:
        os.makedirs(os.path.dirname(CURSOR_FILE), exist_ok=True)
        with open(CURSOR_FILE, "w") as f:
            f.write(str(ts))
    except Exception as e:
        logger.error(f"Error saving cursor file: {e}")

async def run_backfill(max_days: int):
    logger.info(f"=== STARTING CONTINUOUS NOSTR SPIDER (Max: {max_days} days) ===")
    
    # Initialize the brain (required for unified_monitor.process_source to work)
    from feedo_parser.vector_brain import VectorBrain
    unified_monitor.brain = VectorBrain()
    
    # Initialize our Nostr Source
    from feedo_parser.content_sources import NostrSource
    source = NostrSource()
    
    while True:
        cutoff_ts = int(datetime.utcnow().timestamp()) - (max_days * 86400)
        current_cursor = load_cursor()
        
        # If cursor is missing or older than max_days, reset it to now
        if current_cursor is None or current_cursor < cutoff_ts:
            logger.info("Cursor reached the limit or is missing. Starting a NEW cycle from now.")
            current_cursor = int(datetime.utcnow().timestamp())
            save_cursor(current_cursor)
            
        logger.info(f"🕸️ SPIDER: Crawling users active before {datetime.fromtimestamp(current_cursor, tz=timezone.utc)}")
        
        # Calculate the since_ts for posts. We want the 180-day window for the posts too, 
        # but realistically limit=500 will do the truncation.
        post_since_ts = current_cursor - (180 * 86400)
        
        class BackfillSourceWrapper:
            def __init__(self, original_source):
                self.source_type = original_source.source_type
                self.original = original_source
                
            async def fetch_new_batches(self, since=None, node_index=0, total_nodes=1, db=None):
                async for batch in self.original.fetch_new_batches(
                    since=since, 
                    node_index=node_index, 
                    total_nodes=total_nodes, 
                    db=db, 
                    override_since_ts=post_since_ts,
                    override_until_ts=current_cursor
                ):
                    yield batch

        wrapper = BackfillSourceWrapper(source)
        
        # Get dynamic sharding info from network
        import hashlib
        from unified_monitor import get_network_info
        net_info = await get_network_info()
        peer_id = net_info.get("peer_id", "standalone_node")
        total_nodes = max(1, net_info.get("total_nodes", 1))
        my_id_num = int(hashlib.sha256(peer_id.encode('utf-8')).hexdigest(), 16)
        node_index = my_id_num % total_nodes
        
        logger.info(f"🕷️ SPIDER Sharding: My node {peer_id[:8]}... Total nodes: {total_nodes}. Index: {node_index}")
        
        # Process the batch with dynamic sharding
        await unified_monitor.process_source(wrapper, node_index=node_index, total_nodes=total_nodes)
        
        # After processing, update the cursor to the oldest user we discovered in this batch
        if hasattr(source, "last_min_created_at") and source.last_min_created_at and source.last_min_created_at < current_cursor:
            new_cursor = source.last_min_created_at
            logger.info(f"🕷️ SPIDER: Batch complete. Moving cursor back to {datetime.fromtimestamp(new_cursor, tz=timezone.utc)}")
            save_cursor(new_cursor)
        else:
            logger.warning("SPIDER: Could not determine an older cursor. Sleeping 5 mins to try again.")
            await asyncio.sleep(300)
            
        logger.info("Sleeping 60 seconds before next batch...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Continuous Nostr History Spider")
    parser.add_argument("--days", type=int, default=180, help="Max days to crawl back (default: 180)")
    args = parser.parse_args()
    
    asyncio.run(run_backfill(args.days))
