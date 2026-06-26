import os
import sys
import asyncio
import json

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from database import AsyncSessionLocal
from models import Post
import httpx


async def main(media_hash: str):
    async with AsyncSessionLocal() as db:
        stmt = await db.execute(
            __import__('sqlalchemy').future.select(Post).where(Post.content_blob_hash == media_hash).limit(1)
        )
        post = stmt.scalars().first()
        if not post:
            print(f"No post found with content_blob_hash={media_hash}")
            return 1

        b64_text = getattr(post, 'text_content', None)
        if not b64_text:
            print(f"Post found but no text_content/base64 available for {media_hash}")
            return 2

        rust_publish = os.getenv('RUST_CORE_URL', 'http://127.0.0.1:8041/local/publish')
        payload = {
            'text': b64_text,
            'author': getattr(post, 'author_address', 'network_sync') or 'network_sync',
            'signature': getattr(post, 'signature', '') or '',
            'hash_id': getattr(post, 'hash_id', media_hash) or media_hash,
            'content_blob_hash': media_hash,
            'prev_post_hash': getattr(post, 'prev_post_hash', '') or '',
            'sequence_number': getattr(post, 'sequence_number', 0) or 0,
        }

        print(f"Publishing to Rust at {rust_publish} ...")
        async with httpx.AsyncClient() as client:
            try:
                res = await client.post(rust_publish, json=payload, timeout=60.0)
                print('Status:', res.status_code)
                try:
                    print('Response:', res.text[:1000])
                except Exception:
                    print('Response: <binary>')
            except Exception as e:
                print('Publish failed:', e)
                return 3

    return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python scripts/republish_media.py <media_hash>')
        sys.exit(1)
    media_hash = sys.argv[1].strip()
    code = asyncio.run(main(media_hash))
    sys.exit(code)
