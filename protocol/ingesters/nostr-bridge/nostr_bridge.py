import asyncio
import websockets
import json
import logging
import time
from aiohttp import web

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

import urllib.request
import urllib.error

def fetch_pending():
    req = urllib.request.Request("http://127.0.0.1:8040/internal/nostr/pending_broadcasts")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.error(f"Failed to fetch pending broadcasts: {e}")
        return {"posts": []}

def mark_broadcasted(hash_ids, successful_relays):
    if not hash_ids or not successful_relays:
        return
    req = urllib.request.Request(
        "http://127.0.0.1:8040/internal/nostr/mark_broadcasted",
        data=json.dumps({"hash_ids": hash_ids, "relay_urls": successful_relays}).encode('utf-8'),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            pass
    except Exception as e:
        logger.error(f"Failed to mark broadcasted: {e}")

async def broadcast_pending_loop():
    while True:
        try:
            data = await asyncio.to_thread(fetch_pending)
            posts = data.get("posts", [])
            for p in posts:
                # Construct event
                metadata = p.get("metadata_", {})
                event = {
                    "id": p["hash_id"],
                    "pubkey": p.get("author", "").replace("did:feedo:schnorr:", ""),
                    "created_at": metadata.get("nostr_created_at", int(time.time())),
                    "kind": metadata.get("nostr_kind", 1),
                    "tags": metadata.get("nostr_tags", []),
                    "content": p["text"],
                    "sig": p["signature"]
                }
                
                msg = json.dumps(["EVENT", event])
                success_relays = []
                
                async def _send(url):
                    try:
                        async with websockets.connect(url, open_timeout=2.0) as ws:
                            await ws.send(msg)
                            resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
                            resp_data = json.loads(resp)
                            if isinstance(resp_data, list) and len(resp_data) >= 3 and resp_data[0] == "OK" and resp_data[2]:
                                return url
                    except Exception:
                        pass
                    return None
                
                import random
                target_relays = random.sample(GLOBAL_RELAYS, min(3, len(GLOBAL_RELAYS)))
                results = await asyncio.gather(*[_send(r) for r in target_relays])
                success_relays = [r for r in results if r]
                
                if success_relays:
                    await asyncio.to_thread(mark_broadcasted, [p["hash_id"]], success_relays)
                    logger.info(f"Broadcasted {p['hash_id']} to {len(success_relays)} relays.")
                    
        except Exception as e:
            logger.error(f"Broadcast loop error: {e}")
            
        await asyncio.sleep(10)

async def resolve_event(request):
    hash_id = request.match_info.get('hash_id')
    if not hash_id:
        return web.json_response({"error": "hash_id required"}, status=400)
    
    req = ["REQ", f"resolve_{hash_id}", {"ids": [hash_id]}]
    msg = json.dumps(req)
    
    async def _fetch(url):
        try:
            async with websockets.connect(url, open_timeout=2.0) as ws:
                await ws.send(msg)
                while True:
                    resp = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    resp_data = json.loads(resp)
                    if isinstance(resp_data, list) and len(resp_data) >= 3:
                        if resp_data[0] == "EVENT":
                            return resp_data[2]
                        if resp_data[0] == "EOSE":
                            break
        except Exception:
            pass
        return None

    import random
    target_relays = random.sample(GLOBAL_RELAYS, min(3, len(GLOBAL_RELAYS)))
    results = await asyncio.gather(*[_fetch(r) for r in target_relays])
    
    for r in results:
        if r:
            return web.json_response(r)
            
    return web.json_response({"error": "Event not found on relays"}, status=404)

async def start_http_server():
    app = web.Application()
    app.router.add_get('/resolve/{hash_id}', resolve_event)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8041)
    await site.start()
    logger.info("Internal HTTP server for resolution started on port 8041")

async def main():
    tasks = [fetch_from_relay(url) for url in GLOBAL_RELAYS]
    tasks.append(broadcast_pending_loop())
    tasks.append(start_http_server())
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
