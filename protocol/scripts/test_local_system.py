import asyncio
import httpx
import uuid
import time
import hashlib
import json
import secrets
import sys
import os
from nacl.signing import SigningKey

def generate_keypair():
    key = SigningKey.generate()
    return key.encode().hex(), key.verify_key.encode().hex()

def sign_message(msg: str, priv_hex: str) -> str:
    key = SigningKey(bytes.fromhex(priv_hex))
    try:
        msg_bytes = bytes.fromhex(msg)
    except ValueError:
        msg_bytes = msg.encode('utf-8')
    return key.sign(msg_bytes).signature.hex()

BASE_URL = "http://127.0.0.1:18040/api/v1"

# Terminal Colors for output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    END = '\033[0m'

def print_step(name):
    print(f"\n{Colors.CYAN}=== Testing: {name} ==={Colors.END}")

def print_success(msg):
    print(f"[{Colors.GREEN}PASS{Colors.END}] {msg}")

def print_error(msg):
    print(f"[{Colors.RED}FAIL{Colors.END}] {msg}")

async def test_node_endpoints():
    print_step("Node Info & Metrics")
    async with httpx.AsyncClient() as client:
        # Wait for server to boot (up to 30s)
        for i in range(15):
            try:
                res = await client.get(f"{BASE_URL}/node/health")
                if res.status_code == 200:
                    print_success(f"Health OK: {res.json()}")
                    break
            except Exception:
                pass
            print(f"{Colors.YELLOW}Waiting for server to boot... ({i+1}/15){Colors.END}")
            await asyncio.sleep(2)
        else:
            print_error("Health failed: Server did not respond in time")

        # 2. Metrics
        res = await client.get(f"{BASE_URL}/node/metrics")
        if res.status_code == 200:
            print_success(f"Metrics OK: {res.json()}")
        else:
            print_error(f"Metrics failed: {res.text}")

        # 3. Peers
        res = await client.get(f"{BASE_URL}/node/peers")
        if res.status_code == 200:
            print_success(f"Peers OK: {res.json()}")
        else:
            print_error(f"Peers failed: {res.text}")

def verify_pow(public_key: str, nonce: str, difficulty: int = 4) -> bool:
    data = f"{public_key}:{nonce}".encode('utf-8')
    return hashlib.sha256(data).hexdigest().startswith('0' * difficulty)

def generate_pow(public_key: str, difficulty: int = 4) -> str:
    print(f"{Colors.YELLOW}Generating PoW nonce for {public_key}...{Colors.END}")
    nonce = 0
    while True:
        if verify_pow(public_key, str(nonce), difficulty):
            return str(nonce)
        nonce += 1

async def test_identity_endpoints():
    print_step("Identity & Delegation")
    
    # 1. Generate identity using ed25519
    priv, pubkey = generate_keypair()
    # pubkey is returned as hex string
    
    nonce = generate_pow(pubkey)
    
    metadata = {
        "username": f"test_user_{secrets.token_hex(4)}",
        "name": "Test Local User",
        "bio": "Local testing bio",
    }
    
    # Sign the DID Document
    doc_str = json.dumps(metadata)
    sig = sign_message(doc_str, priv)
    
    payload = {
        "public_key": pubkey,
        "metadata": metadata,
        "signature": sig,
        "pow_nonce": nonce
    }
    
    async with httpx.AsyncClient() as client:
        # 1. Announce
        res = await client.post(f"{BASE_URL}/identity/announce", json=payload)
        if res.status_code == 200:
            print_success(f"Identity announced: {res.json()}")
        else:
            print_error(f"Identity announce failed: {res.text}")
            
        # 2. Get Identities
        res = await client.get(f"{BASE_URL}/identity/")
        if res.status_code == 200:
            print_success(f"Fetched identities list (count: {len(res.json().get('identities', []))})")
        else:
            print_error(f"Failed to fetch identities: {res.text}")
            
        # 3. Get Specific Identity
        res = await client.get(f"{BASE_URL}/identity/{pubkey}")
        if res.status_code == 200:
            print_success(f"Fetched specific identity: {res.json().get('username')}")
        else:
            print_error(f"Failed to fetch specific identity: {res.text}")
            
    return pubkey, priv

async def test_content_endpoints(pubkey, priv):
    print_step("Content Publishing & Vectors")
    
    ts = int(time.time())
    text_content = f"Це тестовий контент для семантичного пошуку. Згенеровано автоматично. {uuid.uuid4()}"
    
    # Hash ID calculation: text_content + "_" + timestamp
    hash_id_raw = f"{text_content}_{ts}"
    hash_id = hashlib.sha256(hash_id_raw.encode('utf-8')).hexdigest()
    
    # Signature of hash_id
    sig = sign_message(hash_id, priv)
    
    payload = {
        "text": text_content,
        "author": pubkey,
        "signature": sig,
        "hash_id": hash_id,
        "content_blob_hash": "empty",
        "title": "Local Test Post",
        "source_type": "native",
        "sequence_number": 1,
        "timestamp": ts,
        "metadata_": {"namespace": "feedo/test"}
    }
    
    async with httpx.AsyncClient() as client:
        # 1. Publish
        res = await client.post(f"{BASE_URL}/content/publish", json=payload)
        if res.status_code == 200:
            print_success(f"Content published to PBFT mempool: {hash_id}")
        else:
            print_error(f"Content publish failed: {res.text}")
            
        # 2. Semantic Search Query
        query_payload = {
            "text": "тестовий контент семантичний",
            "limit": 5,
            "threshold": 0.5
        }
        await asyncio.sleep(2)
        
        res = await client.post(f"{BASE_URL}/semantic/query", json=query_payload)
        if res.status_code == 200:
            results = res.json().get('results', [])
            print_success(f"Semantic search returned {len(results)} results")
            for r in results:
                print(f"   -> Match: {r.get('hash_id')} (Score: {r.get('score')})")
        else:
            print_error(f"Semantic search failed: {res.text}")
            
        # 3. Namespace Search
        res = await client.get(f"{BASE_URL}/semantic/namespace/feedo/test")
        if res.status_code == 200:
            print_success("Namespace fetch successful")
        else:
            print_error(f"Namespace fetch failed: {res.text}")

    return hash_id

async def test_tokenomics(pubkey):
    print_step("Tokenomics & Reputation")
    
    async with httpx.AsyncClient() as client:
        # Deposit
        dep = {"pubkey": pubkey, "amount": 1000}
        res = await client.post(f"{BASE_URL}/tokenomics/deposit", json=dep)
        if res.status_code == 200:
            print_success(f"Token deposit OK: {res.json().get('message')}")
        else:
            print_error(f"Token deposit failed: {res.text}")
            
        # Check Balance
        res = await client.get(f"{BASE_URL}/tokenomics/{pubkey}")
        if res.status_code == 200:
            print_success(f"Balance check OK: {res.json().get('balances')}")
        else:
            print_error(f"Balance check failed: {res.text}")

async def test_crdt_endpoints(pubkey, priv):
    print_step("CRDT Distributed State")
    
    # We will test an AwOrSet CRDT operation
    object_id = f"crdt_test_{secrets.token_hex(4)}"
    
    # Needs to match CrdtMutateRequest schema
    payload = {
        "object_id": object_id,
        "crdt_type": "AwOrSet",
        "operation": "add",
        "key": "test_key",
        "value": "test_value_1",
        "timestamp": int(time.time()),
        "author": pubkey,
        "signature": sign_message(f"{object_id}:test_key:test_value_1", priv),
        "vector_tag": f"tag_{secrets.token_hex(4)}",
        "remove_tags": []
    }
    async with httpx.AsyncClient() as client:
        # Create CRDT op
        res = await client.post(f"{BASE_URL}/crdt/mutate", json=payload)
        if res.status_code == 200:
            print_success(f"CRDT Operation added: {object_id}")
        else:
            print_error(f"CRDT Operation failed: {res.text}")
            
        # Get CRDT state
        res = await client.get(f"{BASE_URL}/crdt/{object_id}")
        if res.status_code == 200:
            print_success(f"CRDT State fetched: {res.json()}")
        else:
            print_error(f"CRDT State fetch failed: {res.text}")

async def test_graph(pubkey, hash_id):
    print_step("Graph Navigation")
    target_hash = "target_" + secrets.token_hex(4)
    payload = {
        "source_hash": hash_id,
        "target_hash": target_hash,
        "edge_type": "reply",
        "signature": "sig",
        "author_address": pubkey
    }
    async with httpx.AsyncClient() as client:
        # Create Edge
        res = await client.post(f"{BASE_URL}/graph/edge", json=payload)
        if res.status_code == 200:
            print_success("Graph edge created successfully")
        else:
            print_error(f"Graph edge creation failed: {res.text}")
            
        # Tree
        res = await client.get(f"{BASE_URL}/graph/tree/{hash_id}")
        if res.status_code == 200:
            print_success(f"Graph tree fetched: {res.json()}")
        else:
            print_error(f"Graph tree fetch failed: {res.text}")


async def main():
    print(f"{Colors.YELLOW}--- Starting Feedo Local System Test Suite ---{Colors.END}")
    
    # Run tests
    await test_node_endpoints()
    pubkey, priv = await test_identity_endpoints()
    hash_id = await test_content_endpoints(pubkey, priv)
    await test_crdt_endpoints(pubkey, priv)
    await test_tokenomics(pubkey)
    await test_graph(pubkey, hash_id)
    
    print(f"\n{Colors.GREEN}--- Test Suite Execution Finished ---{Colors.END}")

if __name__ == "__main__":
    asyncio.run(main())
