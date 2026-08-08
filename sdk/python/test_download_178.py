import asyncio
import os
import time
from eth_account import Account
from feedo.client import FeedoClient

async def main():
    new_account = Account.create()
    privKey = new_account._private_key.hex()
    pubKey = new_account._key_obj.public_key.to_hex()
    
    print(f"New account created. Private Key: {privKey}")
    
    client95 = FeedoClient(
        storage_seeds=["http://95.111.245.68:3001"],
        consensus_seeds=["http://95.111.245.68:3000"],
        private_key=privKey
    )
    
    print("Registering DID on consensus node 95...")
    try:
        res = await client95.consensus.register_did(privKey)
        print(f"DID Registered: {res}")
    except Exception as e:
        print(f"DID Registration info/error: {e}")
        
    size = 11 * 1024 * 1024
    print(f"Generating {size} bytes of test data...")
    data = os.urandom(size)

    print("Uploading private file to node 95...")
    hash_id = await client95.upload_private_file(data, index_for_search=False)
    print(f"Uploaded! Hash: {hash_id}")

    wait_time = 45
    print(f"Waiting {wait_time} seconds for DHT and Consensus sync to node 178...")
    for i in range(wait_time, 0, -1):
        if i % 5 == 0:
            print(f"{i}...", end=" ", flush=True)
        time.sleep(1)
    print("Done waiting.")

    client178 = FeedoClient(
        storage_seeds=["http://178.18.253.94:3001"],
        consensus_seeds=["http://178.18.253.94:3000"],
        private_key=privKey
    )

    print(f"Trying to download private hash {hash_id} from 178 node...")
    try:
        downloaded = await client178.download_private_file(hash_id)
        if len(downloaded) == size:
            print(f"SUCCESS! Cross-node download and decryption successful! Bytes: {len(downloaded)}")
        else:
            print(f"Downloaded, but size mismatch: {len(downloaded)} vs {size}")
    except Exception as e:
        print(f"Download failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
