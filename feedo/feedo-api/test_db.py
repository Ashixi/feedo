import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

engine = create_async_engine('postgresql+asyncpg://postgres:postgres@localhost:5432/feedo')

async def run():
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT text_content FROM posts WHERE hash_id='0000d8b47088d26d6ccb4267852312c9a52e291076ca1c4e3e03817a456c1dd3'"))
        print(repr(res.scalar()))

asyncio.run(run())
