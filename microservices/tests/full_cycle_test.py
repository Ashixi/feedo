#!/usr/bin/env python3
"""
Full-Cycle Integration Test: All 3 services

Запускає всі 3 сервіси на окремих портах:
  - storage-node (Rust, HTTP=3050)
  - consensus-node (Rust, HTTP=3008)
  - search-node (Python, HTTP=8003)

Тестує повний цикл:
  DID -> Name -> Upload -> CID Bind -> Resolve -> Vectorize -> Search -> Download -> Cleanup

Run:
    cd microservices\tests
    python full_cycle_test.py

Prerequisites:
    cargo build --bin consensus-node
    cargo build --bin storage-node
    pip install -r search-node/requirements.txt
"""

import os
import sys
import json
import time
import zipfile
import shutil
import tempfile
import subprocess
import requests
from pathlib import Path

# --- Config ---
STORAGE_HTTP = "http://127.0.0.1:3050"
CONSENSUS_HTTP = "http://127.0.0.1:3008"
SEARCH_HTTP = "http://127.0.0.1:8003"

STORAGE_DB = "test_fc_storage"
CONSENSUS_DB = "test_fc_consensus"
SEARCH_DB = "./test_fc_search_db"

# --- Helpers ---

def find_binary(name):
    candidates = [
        f"../target/debug/{name}.exe",
        f"../target/debug/{name}",
    ]
    for c in candidates:
        p = Path(c)
        if p.exists():
            return str(p.resolve())
    raise FileNotFoundError(f"{name} not found. Build with: cargo build --bin {name}")


def wait_for_http(url, timeout=120, label=""):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=2)
            print(f"  [{label}] {url} -> {r.status_code}")
            return True
        except Exception:
            time.sleep(1)
    return False


def make_test_zip(title, body):
    """Create a test zip with index.html in memory."""
    tmpdir = tempfile.mkdtemp()
    index_path = os.path.join(tmpdir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html><head><title>{title}</title></head>
<body><h1>{title}</h1><p>{body}</p></body></html>""")
    zip_path = os.path.join(tmpdir, "site.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(index_path, "index.html")
    with open(zip_path, "rb") as f:
        data = f.read()
    shutil.rmtree(tmpdir)
    return data


# --- Test ---

def test_full_cycle():
    storage_proc = None
    consensus_proc = None
    search_proc = None
    did = None
    cid = None

    try:
        # ============ Start Services ============
        print("\n[SETUP] Starting storage-node...")
        storage_bin = find_binary("storage-node")
        shutil.rmtree(STORAGE_DB, ignore_errors=True)
        storage_proc = subprocess.Popen(
            [storage_bin],
            env={**os.environ, "HTTP_PORT": "3050", "P2P_PORT": "8050",
                 "GRPC_PORT": "50060", "DB_DIR": STORAGE_DB},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"  Storage PID: {storage_proc.pid}")
        assert wait_for_http(STORAGE_HTTP, timeout=15, label="storage"), "Storage timeout"

        print("\n[SETUP] Starting consensus-node...")
        consensus_bin = find_binary("consensus-node")
        shutil.rmtree(CONSENSUS_DB, ignore_errors=True)
        consensus_proc = subprocess.Popen(
            [consensus_bin],
            env={**os.environ, "HTTP_PORT": "3008", "P2P_PORT": "8051",
                 "GRPC_PORT": "50061", "DB_DIR": CONSENSUS_DB,
                 "NODE_WALLET_ADDRESS": "0xcccccccccccccccccccccccccccccccccccccccc",
                 "ETH_RPC_URL": "https://polygon-rpc.com"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"  Consensus PID: {consensus_proc.pid}")
        assert wait_for_http(CONSENSUS_HTTP, timeout=20, label="consensus"), "Consensus timeout"

        print("\n[SETUP] Starting search-node...")
        print("  (ML models loading, may take 60-120s first run)")
        shutil.rmtree(SEARCH_DB, ignore_errors=True)
        search_script = Path(__file__).parent.parent / "search-node" / "main.py"
        search_proc = subprocess.Popen(
            [sys.executable, str(search_script)],
            env={**os.environ, "PORT": "8003", "STORAGE_NODE_URL": STORAGE_HTTP,
                 "LANCE_DB_PATH": SEARCH_DB, "KNOWN_PEERS": ""},
            cwd=str(search_script.parent),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"  Search PID: {search_proc.pid}")
        assert wait_for_http(SEARCH_HTTP, timeout=180, label="search"), "Search timeout"
        time.sleep(2)

        # ============ TEST 1: Register DID ============
        print("\n========== TEST 1: Register DID ==========")
        from eth_account import Account
        from eth_account.messages import encode_defunct
        
        priv_hex = "11" * 32
        acct = Account.from_key(priv_hex)
        pub_hex = acct.address  # Ethereum address (consensus-node uses address as public_key)

        resp = requests.post(f"{CONSENSUS_HTTP}/did/register",
                             json={"public_key": pub_hex}, timeout=10)
        assert resp.status_code == 200, f"DID reg failed: {resp.text}"
        did = resp.json()["did"]
        print(f"  [OK] DID registered: {did}")

        # ============ TEST 2: Upload zip to storage ============
        print("\n========== TEST 2: Upload zip to storage ==========")
        zip_data = make_test_zip("FullCycle Test", "Full cycle integration test site")
        resp = requests.post(f"{STORAGE_HTTP}/upload",
                             files={"file": ("site.zip", zip_data, "application/zip")}, timeout=15)
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        cid = resp.text.strip()
        assert len(cid) == 64, f"Expected 64-char SHA256, got {len(cid)}"
        print(f"  [OK] Uploaded: CID={cid}")

        # ============ TEST 3: Register name ============
        print("\n========== TEST 3: Register domain name ==========")
        name = "fullcycle.feedo"
        payload = f"{name}{did}"
        msg = encode_defunct(text=payload)
        sig_obj = acct.sign_message(msg)
        sig_hex = "0x" + sig_obj.signature.hex()

        resp = requests.post(f"{CONSENSUS_HTTP}/name/register",
                             json={"name": name, "did": did, "public_key": pub_hex,
                                   "signature": sig_hex}, timeout=10)
        assert resp.status_code == 200, f"Name reg failed: {resp.text}"
        assert resp.json().get("success"), f"Name reg not successful: {resp.text}"
        print(f"  [OK] Name registered: {name}")

        # ============ TEST 4: Bind CID to domain ============
        print("\n========== TEST 4: Bind CID to domain ==========")
        cid_payload = f"{name}{cid}"
        cid_msg = encode_defunct(text=cid_payload)
        cid_sig_obj = acct.sign_message(cid_msg)
        cid_sig_hex = "0x" + cid_sig_obj.signature.hex()

        resp = requests.post(f"{CONSENSUS_HTTP}/name/update_cid",
                             json={"name": name, "cid": cid, "signature": cid_sig_hex,
                                   "gateways": ["http://gateway.feedo.ink"]}, timeout=10)
        assert resp.status_code == 200, f"CID update failed: {resp.text}"
        print(f"  [OK] CID bound: {name} -> {cid}")

        # ============ TEST 5: Resolve ============
        print("\n========== TEST 5: Resolve domain ==========")
        time.sleep(2)
        resp = requests.get(f"{CONSENSUS_HTTP}/resolve/{name}", timeout=10)
        assert resp.status_code == 200
        resolve_data = resp.json()
        print(f"  Resolve: {json.dumps(resolve_data)}")
        assert resolve_data and resolve_data.get("cid") == cid, \
            f"CID mismatch: expected {cid}, got {resolve_data.get('cid')}"
        print(f"  [OK] Domain resolves to correct CID")

        # ============ TEST 6: Download from storage ============
        print("\n========== TEST 6: Download from storage ==========")
        resp = requests.get(f"{STORAGE_HTTP}/download/{cid}", timeout=10)
        assert resp.status_code == 200, f"Download failed: {resp.status_code}"
        assert resp.content == zip_data, "Downloaded data mismatch"
        print(f"  [OK] Storage download matches ({len(resp.content)} bytes)")

        # ============ TEST 7: Vectorize & Search ============
        print("\n========== TEST 7: Vectorize and search ==========")
        # Index via search-node (separate from publish_feedo to simulate manual indexing)
        resp = requests.post(f"{SEARCH_HTTP}/index_document",
                             json={"hash_id": cid, "text": "Full cycle integration test site",
                                   "item_type": "website",
                                   "metadata": {"title": "FullCycle Test", "domain": name}},
                             timeout=10)
        assert resp.status_code == 200, f"Index failed: {resp.text}"
        print(f"  [OK] Document indexed in search-node")

        time.sleep(3)
        resp = requests.get(f"{SEARCH_HTTP}/query",
                            params={"text": "full cycle integration", "item_type": "website", "limit": 5},
                            timeout=15)
        results = resp.json().get("results", [])
        found = any(r.get("hash_id") == cid for r in results)
        assert found, f"Site not found in search results (got {len(results)} results)"
        print(f"  [OK] Site found in search ({len(results)} results)")

        # ============ TEST 8: Cleanup ============
        print("\n========== TEST 8: Cleanup ==========")
        requests.delete(f"{SEARCH_HTTP}/proxy/unpin_feedo/{cid}", timeout=10)
        requests.delete(f"{STORAGE_HTTP}/delete/{cid}", timeout=10)
        print(f"  [OK] Cleanup complete")

        print("\n========== FULL CYCLE TEST PASSED ==========")

    finally:
        for proc, name in [(search_proc, "search-node"),
                            (consensus_proc, "consensus-node"),
                            (storage_proc, "storage-node")]:
            if proc:
                print(f"[TEARDOWN] Killing {name} (PID={proc.pid})...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        for d in [STORAGE_DB, CONSENSUS_DB, SEARCH_DB]:
            shutil.rmtree(d, ignore_errors=True)
        for db in Path(".").glob("test_db*"):
            shutil.rmtree(db, ignore_errors=True)
        print("[TEARDOWN] Done")


if __name__ == "__main__":
    test_full_cycle()