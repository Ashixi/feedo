import asyncio
from sqlalchemy import select
from database import AsyncSessionLocal
from models import Post
from langdetect import detect
from sqlalchemy.orm.attributes import flag_modified

async def backfill():
    print("Починаємо оновлення мови для старих постів...")
    async with AsyncSessionLocal() as db:
        stmt = select(Post).where(Post.language == None)
        posts = (await db.execute(stmt)).scalars().all()
        print(f"Знайдено {len(posts)} постів без мови. Оновлюємо...")
        
        count = 0
        for p in posts:
            if p.text_content and len(p.text_content.strip()) > 5:
                try:
                    lang = detect(p.text_content)
                except Exception:
                    lang = 'uk'
                
                p.language = lang
                
                meta = p.metadata_ or {}
                if isinstance(meta, dict):
                    meta["language"] = lang
                    p.metadata_ = meta
                    flag_modified(p, "metadata_")
                
                count += 1
                if count % 100 == 0:
                    await db.commit()
                    print(f"Оновлено {count} постів...")
                    
        await db.commit()
        print(f"Готово! Всього оновлено {count} постів.")

if __name__ == "__main__":
    asyncio.run(backfill())
