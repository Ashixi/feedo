import asyncio
import websockets
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("feedo_proxy")

# The URL of the local or remote standard Nostr relay we are proxying
NOSTR_RELAY_URL = "ws://127.0.0.1:3000"
FEEDo_API_URL = "http://127.0.0.1:8040/api/v1/content/publish"

async def nostr_listener():
    """
    Connects to a standard Nostr relay, subscribes to new events,
    and forwards them to the Feedo Semantic Layer for vectorization.
    """
    logger.info(f"Connecting to Nostr relay at {NOSTR_RELAY_URL}...")
    try:
        async with websockets.connect(NOSTR_RELAY_URL) as websocket:
            logger.info("Connected! Sending REQ subscription...")
            
            # Subscribe to all Text Notes (kind: 1)
            req = ["REQ", "feedo_proxy_sync", {"kinds": [1]}]
            await websocket.send(json.dumps(req))
            
            async for message in websocket:
                data = json.loads(message)
                if isinstance(data, list) and len(data) >= 3 and data[0] == "EVENT":
                    event = data[2]
                    logger.info(f"Received new Nostr event: {event.get('id')}")
                    # TODO: Transform to FeedoBroadcast and send to Feedo API
             
                        
    except Exception as e:
        logger.error(f"Proxy error: {e}")

if __name__ == "__main__":
    asyncio.run(nostr_listener())
