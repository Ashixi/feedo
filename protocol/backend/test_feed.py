import asyncio
from database import SessionLocal
from services.feed_service import FeedService
from services.vector_service import VectorBrain

async def test():
    brain = VectorBrain()
    async with SessionLocal() as db:
        res = await FeedService.generate_feed(db, brain, limit=50, offset=0, source_type='nostr', language='en', text='bitcoin')
        print(f"Result count: {len(res[0])}")
        print("Hash IDs:")
        for r in res[0]:
            print(r[1].hash_id)

asyncio.run(test())
