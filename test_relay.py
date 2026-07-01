import asyncio
import websockets
import json

async def main():
    async with websockets.connect("wss://yabu.me") as ws:
        req = ["REQ", "test1", {"ids": ["dbc4b394cc525fa2ebc53d713a81bb657292ecef89a31a4b514dafa556188534"]}]
        await ws.send(json.dumps(req))
        print(f"Sent: {req}")
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"Received: {msg}")

asyncio.run(main())
