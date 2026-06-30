import asyncio
import json
import websockets

async def test_resolve(hash_id):
    req = ["REQ", f"resolve_{hash_id}", {"ids": [hash_id]}]
    msg = json.dumps(req)
    
    url = "wss://relay.damus.io"
    try:
        async with websockets.connect(url, open_timeout=5.0) as ws:
            await ws.send(msg)
            while True:
                resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                resp_data = json.loads(resp)
                if isinstance(resp_data, list) and len(resp_data) >= 3:
                    if resp_data[0] == "EVENT":
                        return resp_data[2]
                    if resp_data[0] == "EOSE":
                        break
    except Exception as e:
        print(f"Error: {e}")
    return None

if __name__ == "__main__":
    event_id = "7b3800ae120d21577b41252806e3a2cfeaaa6bf3943443dfec220cfb655631f1"
    res = asyncio.run(test_resolve(event_id))
    print("Found:", res)
