import asyncio
import os
import sys
import httpx
from datetime import datetime, timedelta, timezone

# Add the parent directory to sys.path to import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import AsyncSessionLocal
from sqlalchemy import select, update
from models import Post

async def prune_old_content():
    """
    Finds posts older than 30 days and sends a request to the Rust P2P node
    to delete their content from the decentralized Feedo Network.
    """
    print("Starting P2P content pruning job...")
    thirty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    rust_core_url = os.environ.get("RUST_CORE_URL", "http://127.0.0.1:8041/local/publish")
    base_rust_url = rust_core_url.replace("/local/publish", "")
    
    async with AsyncSessionLocal() as session:
        # We need to find posts older than 30 days that are marked as having content in P2P.
        # Since we just search by date, we can fetch all of them. To avoid re-deleting, 
        # you might want to add a boolean flag `is_purged_from_p2p` in the database later.
        stmt = select(Post.hash_id).where(
            Post.published_at < thirty_days_ago,
            Post.source_type == "nostr" # Target Nostr posts
        ).limit(5000) # Process in chunks of 5000
        
        old_post_hashes = (await session.execute(stmt)).scalars().all()
        
        if not old_post_hashes:
            print("No old posts to prune.")
            return

        print(f"Found {len(old_post_hashes)} posts older than 30 days. Sending delete requests to Rust node...")

        async with httpx.AsyncClient() as client:
            count = 0
            for hash_id in old_post_hashes:
                # TODO: Implement this endpoint in the Rust node to delete chunks by hash_id!
                delete_url = f"{base_rust_url}/local/delete_hash/{hash_id}"
                try:
                    # We use a POST request depending on how you implement it in Rust
                    res = await client.post(delete_url, timeout=2.0)
                    if res.status_code == 200:
                        count += 1
                except Exception as e:
                    pass # Node might not have implemented it yet or network error
                    
                if count % 100 == 0 and count > 0:
                    print(f"Issued {count} delete requests to P2P network...")

        print(f"P2P Pruning complete. Issued {count} delete requests.")

if __name__ == "__main__":
    asyncio.run(prune_old_content())
