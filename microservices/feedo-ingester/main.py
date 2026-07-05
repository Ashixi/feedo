import asyncio
import websockets
import json
import logging
import time
import aiohttp
import secp256k1
import hashlib
from nostr_kinds import extract_data_for_vectorization

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("feedo_ingester")

import os

# Fallback Gateways
GATEWAYS_ENV = os.getenv("GATEWAYS", "")
if GATEWAYS_ENV:
    GATEWAYS = [g.strip() for g in GATEWAYS_ENV.split(",") if g.strip()]
else:
    GATEWAYS = [
        os.getenv("STORAGE_NODE_URL", "http://127.0.0.1:8040"),
        "https://gateway1.feedo.network"
    ]

# Search Node URL
SEARCH_NODE_URL = os.getenv("SEARCH_NODE_URL", "http://127.0.0.1:8000")

# Default seed relays (we will discover more via NIP-65 later)
SEED_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band"
]

class NostrIngester:
    def __init__(self):
        self.active_relays = set(SEED_RELAYS)
        self.running_tasks = set()
        self.processed_events = set()
        self.known_profiles = set()
        
    def verify_schnorr(self, pubkey_hex: str, event_id: str, sig_hex: str) -> bool:
        """Verify the Schnorr signature of a Nostr event."""
        try:
            pubkey_bytes = bytes.fromhex(pubkey_hex)
            sig_bytes = bytes.fromhex(sig_hex)
            msg_bytes = bytes.fromhex(event_id)
            
            pubkey = secp256k1.PublicKey(b'\x02' + pubkey_bytes, True)
            return pubkey.schnorr_verify(msg_bytes, sig_bytes, None, raw=True)
        except Exception as e:
            return False
            
    async def forward_to_storage(self, event: dict, extracted_data: dict):
        """Send the cleaned text and metadata to the PubSub network via a Gateway."""
        data_payload = {
            "hash_id": event["id"],
            "author": f"did:feedo:schnorr:{event['pubkey']}",
            "text": extracted_data["text"],
            "target_hash": extracted_data["target_hash"],
            "signature": event["sig"],
            "metadata": {
                "nostr_kind": event["kind"],
                "nostr_created_at": event["created_at"],
                "nostr_tags": event["tags"]
            },
            # CRITICAL: Memory Optimization. Content will be dropped after 30 days
            # leaving only semantic vector and metadata in the DHT.
            "ttl_days": 30
        }
        
        pubsub_payload = {
            "topic": "feedo_new_events",
            "data": data_payload
        }
        
        async with aiohttp.ClientSession() as session:
            for gateway in GATEWAYS:
                try:
                    async with session.post(f"{gateway}/api/v1/pubsub/publish", json=pubsub_payload, timeout=5.0) as resp:
                        if resp.status == 200:
                            logger.info(f"✅ Published {event['id']} to PubSub via {gateway}")
                            return  # Success, exit the fallback loop
                        else:
                            logger.warning(f"⚠️ Gateway {gateway} returned status {resp.status}, trying next...")
                except Exception as e:
                    logger.warning(f"⚠️ Gateway {gateway} failed ({e}), trying next...")
            
            logger.error(f"❌ Failed to publish {event['id']}: All gateways are unreachable.")

    async def fetch_from_relay(self, relay_url: str):
        while True:
            logger.info(f"Connecting to {relay_url}...")
            try:
                async with websockets.connect(relay_url) as ws:
                    # Subscribe to multiple kinds
                    kinds = [0, 1, 30023, 9735, 40]
                    since_time = int(time.time()) - (24 * 60 * 60)
                    req = ["REQ", f"feedo_spider", {"kinds": kinds, "since": since_time, "limit": 100}]
                    await ws.send(json.dumps(req))
                    
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            if isinstance(data, list) and len(data) >= 3 and data[0] == "EVENT":
                                event = data[2]
                                event_id = event.get('id')
                                
                                if event_id in self.processed_events:
                                    continue
                                self.processed_events.add(event_id)
                                
                                # 1. Cryptographic Validation
                                if not self.verify_schnorr(event['pubkey'], event_id, event['sig']):
                                    logger.warning(f"Invalid signature for event {event_id}")
                                    continue
                                    
                                # 2. Semantic Translation & Reply Filtering
                                extracted = extract_data_for_vectorization(event)
                                if not extracted or not extracted["text"] or len(extracted["text"].strip()) < 5:
                                    continue
                                    
                                # 3. Dynamic Spidering (NIP-65 Kind 10002) - Add to active_relays
                                if event.get('kind') == 10002:
                                    for tag in event.get('tags', []):
                                        if tag[0] == 'r':
                                            self.active_relays.add(tag[1])
                                            
                                # 4. Automatic Profile Backfiller (Disk-backed via search-node)
                                pubkey = event['pubkey']
                                if event.get('kind') == 0:
                                    self.known_profiles.add(pubkey)
                                elif pubkey not in self.known_profiles:
                                    # Check search-node (disk)
                                    async with aiohttp.ClientSession() as session:
                                        try:
                                            check_resp = await session.get(f"{SEARCH_NODE_URL}/profiles/check?pubkey={pubkey}", timeout=2.0)
                                            data = await check_resp.json()
                                            if data.get("exists"):
                                                self.known_profiles.add(pubkey)
                                            else:
                                                logger.info(f"👤 Author {pubkey} not found on disk, requesting profile from relay...")
                                                profile_req = ["REQ", f"profile_{pubkey}", {"kinds": [0], "authors": [pubkey], "limit": 1}]
                                                await ws.send(json.dumps(profile_req))
                                                self.known_profiles.add(pubkey) # Prevent duplicate requests while fetching
                                        except Exception as e:
                                            logger.warning(f"Failed to check profile on disk: {e}")
                                            
                                # 5. Forward to network
                                await self.forward_to_storage(event, extracted)
                                
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")
            except Exception as e:
                logger.error(f"Connection lost to {relay_url}: {e}")
                await asyncio.sleep(10)

    async def dynamic_spider_manager(self):
        """Continuously checks for new relays and spawns tasks for them."""
        while True:
            for relay in list(self.active_relays):
                if relay not in self.running_tasks:
                    logger.info(f"🕸️ Spider spinning new thread for {relay}")
                    self.running_tasks.add(relay)
                    asyncio.create_task(self.fetch_from_relay(relay))
            
            # Simple cleanup for memory leak prevention
            if len(self.known_profiles) > 100000:
                self.known_profiles.clear()
                
            await asyncio.sleep(5)

    async def run(self):
        # Start the dynamic spider manager
        await self.dynamic_spider_manager()

if __name__ == "__main__":
    spider = NostrIngester()
    asyncio.run(spider.run())
