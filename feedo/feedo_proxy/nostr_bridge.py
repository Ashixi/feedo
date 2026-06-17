import asyncio
import websockets
import json
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("feedo_proxy")

GLOBAL_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band"
]

LOCAL_RELAY_URL = "ws://127.0.0.1:8080"

async def fetch_from_relay(relay_url):
    while True:
        logger.info(f"Connecting to global relay at {relay_url}...")
        try:
            async with websockets.connect(relay_url) as global_ws:
                async with websockets.connect(LOCAL_RELAY_URL) as local_ws:
                    logger.info(f"Connected to {relay_url} and local relay.")
                    
                    # Subscribe to all Text Notes (kind: 1) for the last 7 days
                    since_time = int(time.time()) - (7 * 24 * 60 * 60)
                    req = ["REQ", f"feedo_sync_{int(time.time())}", {"kinds": [1], "since": since_time, "limit": 500}]
                    await global_ws.send(json.dumps(req))
                    
                    async for message in global_ws:
                        try:
                            data = json.loads(message)
                            if isinstance(data, list) and len(data) >= 3 and data[0] == "EVENT":
                                event = data[2]
                                logger.info(f"Syncing Nostr event from {relay_url}: {event.get('id')}")
                                
                                # Forward to local relay as a standard publish
                                publish_msg = ["EVENT", event]
                                await local_ws.send(json.dumps(publish_msg))
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")
                            
        except Exception as e:
            logger.error(f"Proxy error for {relay_url}: {e}")
            await asyncio.sleep(5) # Wait before reconnecting

async def main():
    tasks = [fetch_from_relay(url) for url in GLOBAL_RELAYS]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
