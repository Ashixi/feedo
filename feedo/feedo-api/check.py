import asyncio
from database import AsyncSessionLocal
from sqlalchemy.future import select
from models import Post

async def main():
    async with AsyncSessionLocal() as db:
        stmt = select(Post).where(Post.content_blob_hash == 'a384a78191fc3d72f34352a72e82d24138df4c06971b55d2e157a6b4db283287')
        res = (await db.execute(stmt)).scalars().all()
        for p in res:
            print(f"ID: {p.id} ({type(p.id)}), parent_post_id: {p.parent_post_id} ({type(p.parent_post_id)})")

asyncio.run(main())
