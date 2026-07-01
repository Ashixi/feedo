import asyncio
import os
import sys
import logging
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models import Post
from services.vector_service import VectorBrain

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/feedo")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def main():
    brain = VectorBrain()
    logging.info("Starting reindexing from PostgreSQL to LanceDB...")
    
    async with AsyncSessionLocal() as session:
        # Fetch all posts
        stmt = select(Post)
        result = await session.execute(stmt)
        posts = result.scalars().all()
        
        logging.info(f"Found {len(posts)} posts in PostgreSQL.")
        
        count = 0
        for post in posts:
            if not post.text_content and not post.item_type == 'profile':
                # Skip posts with no text/content for vectors? Actually VectorBrain handles empty text
                pass
                
            text_to_embed = post.text_content or ""
            if post.item_type == 'profile':
                text_to_embed = f"{post.display_author} {post.text_content or ''}"
                
            try:
                await brain.add_vector_async(
                    post_id=post.id,
                    hash_id=post.hash_id,
                    text=text_to_embed,
                    source_type=post.source_type or "native",
                    item_type=post.item_type or "post",
                    language=post.language or "",
                    geo="",
                    image_vector=None,
                    relay_url=post.metadata_.get('proxy', '') if getattr(post, 'metadata_', None) else ""
                )
                count += 1
                if count % 100 == 0:
                    logging.info(f"Indexed {count}/{len(posts)} posts...")
            except Exception as e:
                logging.error(f"Error indexing post {post.id}: {e}")
                
        logging.info(f"Finished indexing {count} items.")

if __name__ == "__main__":
    asyncio.run(main())
