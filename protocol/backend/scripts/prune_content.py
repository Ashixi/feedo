import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

# Add the parent directory to sys.path to import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import AsyncSessionLocal
from sqlalchemy import select, update
from models import Post

async def prune_old_content():
    """
    Clears `text_content` and `compressed_content` from posts older than 30 days.
    This frees up local database space. The metadata and vectors remain, 
    and the actual content is available via the P2P Reed-Solomon layer using `hash_id`.
    """
    print("Starting content pruning job...")
    thirty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    
    async with AsyncSessionLocal() as session:
        # Find how many posts are older than 30 days and still have text
        stmt = select(Post.id).where(
            Post.published_at < thirty_days_ago,
            (Post.text_content != None) | (Post.compressed_content != None)
        )
        old_post_ids = (await session.execute(stmt)).scalars().all()
        
        if not old_post_ids:
            print("No old posts to prune.")
            return

        print(f"Found {len(old_post_ids)} posts older than 30 days. Pruning...")

        # Batch update in chunks to avoid locking large tables
        chunk_size = 1000
        for i in range(0, len(old_post_ids), chunk_size):
            chunk = old_post_ids[i:i+chunk_size]
            update_stmt = (
                update(Post)
                .where(Post.id.in_(chunk))
                .values(text_content=None, compressed_content=None)
            )
            await session.execute(update_stmt)
            await session.commit()
            print(f"Pruned batch {i//chunk_size + 1}/{(len(old_post_ids)+chunk_size-1)//chunk_size}")

        print("Pruning complete.")

if __name__ == "__main__":
    asyncio.run(prune_old_content())
