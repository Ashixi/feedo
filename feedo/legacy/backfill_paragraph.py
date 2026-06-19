import os
import json
import asyncio
import logging
from datetime import datetime, timezone
import argparse

import unified_monitor

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_paragraph")

STATE_FILE = "/app/db/backfill_paragraph_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading state file: {e}")
    return None

def save_state(current_ts: int, arweave_cursor: str):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({
                "current_ts": current_ts,
                "arweave_cursor": arweave_cursor
            }, f)
    except Exception as e:
        logger.error(f"Error saving state file: {e}")

async def run_backfill(max_days: int):
    logger.info(f"=== STARTING CONTINUOUS PARAGRAPH/MIRROR SPIDER (Max: {max_days} days) ===")
    
    # Initialize the brain (required for unified_monitor.process_source to work)
    from feedo_parser.vector_brain import VectorBrain
    unified_monitor.brain = VectorBrain()
    
    # Initialize our Paragraph Source
    from feedo_parser.content_sources import ParagraphSource
    source = ParagraphSource()
    
    while True:
        cutoff_ts = int(datetime.utcnow().timestamp()) - (max_days * 86400)
        state = load_state()
        
        current_ts = int(datetime.utcnow().timestamp())
        arweave_cursor = None
        
        if state:
            current_ts = state.get("current_ts", current_ts)
            arweave_cursor = state.get("arweave_cursor")
            
        # If cursor is older than max_days, reset it to now and sleep
        if current_ts < cutoff_ts:
            logger.info(f"Spider reached the limit of {max_days} days. Sleeping for 1 hour before starting a NEW cycle...")
            current_ts = int(datetime.utcnow().timestamp())
            arweave_cursor = None
            save_state(current_ts, arweave_cursor)
            await asyncio.sleep(3600)
            
        logger.info(f"🕸️ SPIDER: Crawling Arweave articles. Current TS: {datetime.fromtimestamp(current_ts, tz=timezone.utc)}, Cursor: {arweave_cursor[:10] if arweave_cursor else 'None'}")
        
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
                    arweave_cursor=arweave_cursor
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
        
        # Advance the state using the native Arweave GraphQL cursor
        if hasattr(source, "last_arweave_cursor") and source.last_arweave_cursor:
            new_cursor = source.last_arweave_cursor
            new_ts = source.last_min_created_at if source.last_min_created_at else current_ts
            
            logger.info(f"🕷️ SPIDER: Batch complete. Moving cursor to {new_cursor[:10]}...")
            save_state(new_ts, new_cursor)
        else:
            logger.warning("SPIDER: No new cursor found (end of data or error). Sleeping 5 mins.")
            await asyncio.sleep(300)
            
        logger.info("Sleeping 60 seconds before next batch...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Continuous Paragraph/Mirror History Spider")
    parser.add_argument("--days", type=int, default=180, help="Max days to crawl back (default: 180)")
    args = parser.parse_args()
    
    asyncio.run(run_backfill(args.days))
