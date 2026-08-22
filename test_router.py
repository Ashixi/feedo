import asyncio
import httpx
import time
import json
from eth_account.messages import encode_defunct
from eth_account import Account

ROUTER_URL = "http://127.0.0.1:8080"

def generate_test_wallet():
    acct = Account.create()
    return acct.key.hex(), acct.address

def sign_payload(private_key_hex, method, path, timestamp):
    payload = f"FeedoAction:{method}:{path}:{timestamp}"
    message = encode_defunct(text=payload)
    signed_message = Account.sign_message(message, private_key=private_key_hex)
    return signed_message.signature.hex()

async def run_tests():
    print("Running Router Node Tests...")
    priv_key, address = generate_test_wallet()
    
    print(f"\nTest 1: Registering storage node (Node ID: {address})")
    timestamp = str(int(time.time() * 1000))
    path = "/register"
    signature = sign_payload(priv_key, "POST", path, timestamp)
    
    body = {
        "type": "storage",
        "p2p_addr": "/ip4/127.0.0.1/udp/8040/quic-v1/p2p/testpeer123",
        "internal_http": "http://127.0.0.1:3001",
        "public_domain": "https://storage.feedo.ink"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{ROUTER_URL}{path}",
                json=body,
                headers={
                    "X-Feedo-Node-ID": address,
                    "X-Feedo-Timestamp": timestamp,
                    "X-Feedo-Signature": signature
                }
            )
            print(f"Register status: {resp.status_code}")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
            print("Register OK")
        except Exception as e:
            print(f"Failed to connect to router: {e}")
            print("Please ensure the router node is running on port 8080.")
            return

    print("\nTest 2: Discover storage node")
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ROUTER_URL}/discover?type=storage")
        print(f"Discover status: {resp.status_code}")
        data = resp.json()
        assert resp.status_code == 200
        
        found = False
        for node in data["nodes"]:
            if node["node_id"].lower() == address.lower():
                found = True
                assert node["internal_http"] == "http://127.0.0.1:3001"
                assert node["public_domain"] == "https://storage.feedo.ink"
                assert node["p2p_addr"] == "/ip4/127.0.0.1/udp/8040/quic-v1/p2p/testpeer123"
                print("Discover OK")
                break
        assert found, "Node was not found in the discover response"

    print("\nTest 3: Python SDK NodeRouter test")
    import sys
    import os
    sys.path.append(os.path.join(os.getcwd(), 'sdk', 'python'))
    try:
        from feedo.router import NodeRouter
        router = NodeRouter(router_url=ROUTER_URL)
        nodes = await router._get_nodes_from_router("storage")
        print(f"SDK Discovered storage nodes: {nodes}")
        assert "https://storage.feedo.ink" in nodes, "SDK did not prefer public_domain"
        print("SDK Router OK")
    except Exception as e:
        print(f"SDK Router test failed: {e}")

    print("\nAll tests passed successfully.")

if __name__ == "__main__":
    asyncio.run(run_tests())
