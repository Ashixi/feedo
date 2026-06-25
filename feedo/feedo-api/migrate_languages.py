import asyncio
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import Post
from database import async_session
from langdetect import detect
import sys

async def migrate_languages():
    print("Starting language migration for all posts...")
    
    async with async_session() as session:
        # Fetch all posts where language might be wrong or needs detection
        # We can just check all posts that have text_content
        stmt = select(Post).where(Post.text_content.is_not(None))
        result = await session.execute(stmt)
        posts = result.scalars().all()
        
        print(f"Found {len(posts)} posts to analyze.")
        
        updated_count = 0
        error_count = 0
        
        for i, post in enumerate(posts):
            if not post.text_content or len(post.text_content.strip()) < 5:
                continue
                
            try:
                detected_lang = detect(post.text_content)
                if post.language != detected_lang:
                    post.language = detected_lang
                    updated_count += 1
            except Exception as e:
                error_count += 1
                
            if i % 1000 == 0:
                print(f"Processed {i}/{len(posts)} posts...")
                await session.commit()
                
        await session.commit()
        print(f"Migration complete! Updated {updated_count} posts. Errors/Undetectable: {error_count}")

if __name__ == "__main__":
    asyncio.run(migrate_languages())
