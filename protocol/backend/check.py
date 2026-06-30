import asyncio
from database import AsyncSessionLocal, engine
from models import UserFeedCache
from sqlalchemy import select

async def run():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(UserFeedCache))
        caches = res.scalars().all()
        print([len(c.feed_hash_ids) for c in caches])
    await engine.dispose()

asyncio.run(run())
