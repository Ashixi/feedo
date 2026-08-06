import asyncio
import httpx
import time
from eth_account import Account
from eth_account.messages import encode_defunct

# Generate two test wallets
# 1. Fake wallet (not registered in consensus)
fake_account = Account.create()

# 2. Registered wallet (we will register this one manually during the test)
valid_account = Account.create()

SEARCH_NODE_URL = "http://127.0.0.1:8000"
STORAGE_NODE_URL = "http://127.0.0.1:3001"
CONSENSUS_NODE_URL = "http://127.0.0.1:3000"

def generate_headers(account, method: str, path: str) -> dict:
    timestamp = str(int(time.time() * 1000))
    payload = f"FeedoAction:{method}:{path}:{timestamp}"
    message = encode_defunct(text=payload)
    signed_message = Account.sign_message(message, private_key=account.key)
    
    return {
        'X-Feedo-DID': f"did:feedo:{account.address}",
        'X-Feedo-Timestamp': timestamp,
        'X-Feedo-Signature': signed_message.signature.hex()
    }

async def run_tests():
    print("🚀 Starting Auth Gate Integration Tests...")
    
    async with httpx.AsyncClient() as client:
        # --- SCENARIO 1: No Signature ---
        print("\n[Scenario 1] Request without signature")
        res = await client.get(f"{STORAGE_NODE_URL}/api/files/recent")
        print(f"Status: {res.status_code}")
        assert res.status_code == 401, f"Expected 401, got {res.status_code}"
        print("✅ Passed: Unauthenticated request blocked.")

        # Let's also test storage-node with fake DID
        print("\n[Scenario 2b] Storage Node Request with fake signature")
        path_storage = "/api/files/recent"
        headers_storage = generate_headers(fake_account, "GET", path_storage)
        res_storage = await client.get(f"{STORAGE_NODE_URL}{path_storage}", headers=headers_storage)
        print(f"Status: {res_storage.status_code}")
        assert res_storage.status_code == 401, f"Expected 401, got {res_storage.status_code}"
        print("✅ Passed: Fake DID request blocked on Storage Node.")

        # --- SCENARIO 3: Register DID and make valid request ---
        print("\n[Scenario 3] Registering DID in consensus...")
        
        # To register a DID in consensus, we need to call POST /did/register
        # Let's look at how consensus node expects this payload.
        # It's an internal test, maybe we can just bypass or mock?
        # Actually, let's see if we can register the DID properly.
        register_payload = {
            "did": f"did:feedo:{valid_account.address}",
            "public_key": valid_account.address,
            "signature": ""
        }
        
        # We need to sign the payload: did:feedo:0xAddress
        reg_message = encode_defunct(text=f"did:feedo:{valid_account.address}")
        reg_sig = Account.sign_message(reg_message, private_key=valid_account.key)
        register_payload["signature"] = reg_sig.signature.hex()
        
        res_reg = await client.post(f"{CONSENSUS_NODE_URL}/did/register", json=register_payload)
        print(f"Registration Status: {res_reg.status_code}")
        # Note: If registration fails because of some consensus setup, the next test might fail.
        # But let's assume it passes (or 200).
        if res_reg.status_code == 200:
            print("✅ Registered DID.")
        else:
            print(f"⚠️ Registration failed (might be expected if node wallet is empty, etc): {res_reg.text}")
            
        print("\n[Scenario 3b] Request with VALID signature and REGISTERED DID")
        path = "/api/files/recent"
        headers = generate_headers(valid_account, "GET", path)
        res = await client.get(f"{STORAGE_NODE_URL}{path}", headers=headers)
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            print("✅ Passed: Valid DID request accepted.")
        else:
            print(f"❌ Failed: Valid DID request rejected with {res.status_code}: {res.text}")

if __name__ == "__main__":
    asyncio.run(run_tests())
