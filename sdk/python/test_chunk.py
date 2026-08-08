import asyncio
import os
from feedo.client import FeedoClient

async def main():
    size = 11 * 1024 * 1024
    print(f"Generating {size} bytes...")
    data = os.urandom(size)
    
    privKey = "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    client = FeedoClient(private_key=privKey)
    
    print("Testing upload_bytes...")
    hash_id = await client.storage.upload_bytes(data, "test.bin")
    print(f"Uploaded! Hash: {hash_id}")

    # We won't test download immediately because DHT takes a few seconds to propagate.
    # print("Testing download_file...")
    # await client.storage.download_file(hash_id)

    print("Testing upload_private_file...")
    priv_hash = await client.upload_private_file(data, index_for_search=False)
    print(f"Uploaded private! Hash: {priv_hash}")

if __name__ == "__main__":
    asyncio.run(main())
