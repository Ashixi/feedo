import asyncio
import asyncpg
import json

async def main():
    conn = await asyncpg.connect('postgresql://feedo:feedo@localhost:5432/feedo')
    rows = await conn.fetch("SELECT hash_id, text_content FROM posts WHERE text_content ILIKE '%BarackHusseinObamall%' LIMIT 1;")
    for row in rows:
        print(row['hash_id'])
        print(row['text_content'])
    await conn.close()

asyncio.run(main())
