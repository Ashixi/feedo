import asyncio
import json
import websockets

async def test_resolve(hash_id):
    req = ["REQ", f"resolve_{hash_id}", {"ids": [hash_id]}]
    msg = json.dumps(req)
    
    async def _fetch(url):
        try:
            async with websockets.connect(url, open_timeout=1.5) as ws:
                await ws.send(msg)
                while True:
                    resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    resp_data = json.loads(resp)
                    if isinstance(resp_data, list) and len(resp_data) >= 3:
                        if resp_data[0] == "EVENT":
                            return resp_data[2]
                        if resp_data[0] == "EOSE":
                            break
        except Exception:
            pass
        return None

    # seed_tasks
    seed_relays = [
        "wss://relay.damus.io", "wss://nos.lol", "wss://relay.snort.social",
        "wss://nostr.wine", "wss://relay.nostr.band", "wss://purplepag.es"
    ]
    seed_tasks = [asyncio.create_task(_fetch(r)) for r in seed_relays]
    for coro in asyncio.as_completed(seed_tasks):
        r = await coro
        if r:
            return r
    return None

if __name__ == "__main__":
    event_id = "f6a8e63a3df54fbe8e1bb3f7215c328dbcaaa6086bba46c5921820b22a00c144" # some event
    print(asyncio.run(test_resolve(event_id)))
