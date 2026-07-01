import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import os

from dotenv import load_dotenv
load_dotenv(".env")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
DB_NAME = os.getenv("POSTGRES_DB", "feedo_db")
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}"

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def test():
    async with async_session() as db:
        res = await db.execute(text("SELECT count(*) FROM posts WHERE item_type='post'"))
        count = res.scalar()
        print(f"Total posts: {count}")

        # check feed cache
        res = await db.execute(text("SELECT wallet_address, array_length(feed_hash_ids, 1) FROM user_feed_caches LIMIT 5"))
        for row in res:
            print(f"Cache: {row}")

asyncio.run(test())
