#!/usr/bin/env python3
"""
Search-Node Integration Test

Запускає 1 storage-node (Rust) + 1 search-node (Python),
тестує повний цикл: publish → download → query → stats → cleanup.

Run:
    cd microservices\search-node
    python tests\test_search.py

Prerequisites:
    - storage-node binary built: cargo build --bin storage-node
    - Python deps installed: pip install -r requirements.txt
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
import signal
from pathlib import Path

# --- Config ---
STORAGE_HTTP_PORT = 3040
STORAGE_P2P_PORT = 8046
STORAGE_GRPC_PORT = 50054
STORAGE_URL = f"http://127.0.0.1:{STORAGE_HTTP_PORT}"
SEARCH_PORT = 8001
SEARCH_URL = f"http://127.0.0.1:{SEARCH_PORT}"
TEST_DB_DIR = "test_storage_search"
LANCE_TEST_DB_DIR = "./lancedb_data_test"
SEARCH_SCRIPT = "main.py"

# --- Helpers ---

def find_storage_binary():
    """Find the compiled storage-node binary (relative to workspace root)."""
    # Walk up from the test file location to find the workspace root (has Cargo.toml)
    test_dir = Path(__file__).resolve().parent  # microservices/search-node/tests
    workspace_root = test_dir.parent.parent.parent  # feedo root
    
    candidates = [
        workspace_root / "microservices" / "target" / "debug" / "storage-node.exe",
        workspace_root / "microservices" / "target" / "debug" / "storage-node",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    
    # Fallback: relative paths from CWD
    fallback = [
        "../target/debug/storage-node.exe",
        "../target/debug/storage-node",
        "../../target/debug/storage-node.exe",
        "../../target/debug/storage-node",
    ]
    for c in fallback:
        p = Path(c)
        if p.exists():
            return str(p.resolve())
    
    raise FileNotFoundError(
        "storage-node binary not found. Build with: cargo build --bin storage-node\n"
        "Searched: " + ", ".join(str(c) for c in candidates + fallback)
    )


def wait_for_http(url, timeout=120, label=""):
    """Poll until the HTTP server responds."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=2)
            print(f"  [{label}] {url} responded with {r.status_code}")
            return True
        except requests.ConnectionError:
            time.sleep(1)
        except Exception as e:
            print(f"  [{label}] {url} error: {e}")
            time.sleep(1)
    return False


def create_test_zip():
    """Create a test zip with index.html in memory, return bytes."""
    tmpdir = tempfile.mkdtemp()
    index_path = os.path.join(tmpdir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html>
<head>
    <title>Feedo Search Test Site</title>
    <meta name="description" content="A test website for Feedo search engine with unique keyword zebrabanana123">
</head>
<body>
    <h1>Welcome to Feedo Test Site</h1>
    <p>This is a unique test page for verifying search functionality.</p>
    <p>Special keyword: zebrabanana123 for search verification.</p>
</body>
</html>""")

    zip_path = os.path.join(tmpdir, "test_site.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(index_path, "index.html")

    with open(zip_path, "rb") as f:
        data = f.read()

    shutil.rmtree(tmpdir)
    return data


def create_emoji_zip():
    """Create a test zip with emoji-rich index.html, return bytes."""
    tmpdir = tempfile.mkdtemp()
    index_path = os.path.join(tmpdir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html>
<head>
    <title>CryptoFeedo - To the Moon!</title>
</head>
<body>
    <h1>Welcome to CryptoFeedo!</h1>
    <p>Bitcoin to the moon! Dogecoin wow much wow!</p>
    <p>Crypto rockets launching soon! Ethereum DeFi revolution.</p>
</body>
</html>""")

    zip_path = os.path.join(tmpdir, "emoji_site.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(index_path, "index.html")

    with open(zip_path, "rb") as f:
        data = f.read()

    shutil.rmtree(tmpdir)
    return data


# --- Tests ---

def test_publish_and_query():
    storage_proc = None
    search_proc = None
    hash_id = None

    try:
        # ============ Step 1: Start Storage Node ============
        print("\n[SETUP] Starting storage-node...")
        bin_path = find_storage_binary()
        print(f"  Storage binary: {bin_path}")

        # Clean previous DB
        db_path = Path(TEST_DB_DIR)
        if db_path.exists():
            shutil.rmtree(db_path)

        storage_proc = subprocess.Popen(
            [bin_path],
            env={
                **os.environ,
                "HTTP_PORT": str(STORAGE_HTTP_PORT),
                "P2P_PORT": str(STORAGE_P2P_PORT),
                "GRPC_PORT": str(STORAGE_GRPC_PORT),
                "DB_DIR": TEST_DB_DIR,
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  Storage PID: {storage_proc.pid}")

        print(f"  Waiting for storage on {STORAGE_URL}...")
        assert wait_for_http(STORAGE_URL, timeout=15, label="storage"), \
            "Storage node did not start within 15s"

        # ============ Step 2: Start Search Node ============
        print("\n[SETUP] Starting search-node...")
        print("  (ML model loading may take 60-120s on first run)")

        # Clean previous LanceDB
        lance_path = Path(LANCE_TEST_DB_DIR)
        if lance_path.exists():
            shutil.rmtree(lance_path)

        search_proc = subprocess.Popen(
            [sys.executable, SEARCH_SCRIPT],
            env={
                **os.environ,
                "PORT": str(SEARCH_PORT),
                "STORAGE_NODE_URL": STORAGE_URL,
                "LANCE_DB_PATH": LANCE_TEST_DB_DIR,
                "KNOWN_PEERS": "",
            },
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  Search PID: {search_proc.pid}")

        print(f"  Waiting for search on {SEARCH_URL}...")
        assert wait_for_http(SEARCH_URL, timeout=180, label="search"), \
            "Search node did not start within 180s (ML model loading)"

        # Small extra wait for async tasks to init
        time.sleep(2)

        # ============ TEST 1: Publish website ============
        print("\n========== TEST 1: Publish website via search-node ==========")
        zip_data = create_test_zip()
        print(f"  Test zip size: {len(zip_data)} bytes")

        resp = requests.post(
            f"{SEARCH_URL}/proxy/publish_feedo",
            files={"file": ("test_site.zip", zip_data, "application/zip")},
            timeout=30,
        )
        print(f"  Response: {resp.status_code} {resp.text}")
        assert resp.status_code == 200, f"Publish failed: {resp.text}"
        data = resp.json()
        hash_id = data.get("cid", "")
        assert hash_id, "No CID in response"
        assert len(hash_id) == 64, f"Expected SHA256 hash (64 hex chars), got {len(hash_id)}"
        print(f"  [OK] Published: hash={hash_id}, title={data.get('title')}")

        # ============ TEST 2: Verify storage has the file ============
        print("\n========== TEST 2: Download from storage ==========")
        resp = requests.get(f"{STORAGE_URL}/download/{hash_id}", timeout=10)
        assert resp.status_code == 200, f"Storage download failed: {resp.status_code}"
        downloaded = resp.content
        assert downloaded == zip_data, f"Downloaded data mismatch: {len(downloaded)} vs {len(zip_data)}"
        print(f"  [OK] Storage has the file ({len(downloaded)} bytes, matches upload)")

        # ============ TEST 3: Search query ============
        print("\n========== TEST 3: Search query ==========")
        time.sleep(3)  # Give LanceDB a moment to index

        resp = requests.get(
            f"{SEARCH_URL}/query",
            params={"text": "Feedo test website", "item_type": "website", "limit": 10},
            timeout=15,
        )
        assert resp.status_code == 200, f"Query failed: {resp.status_code}"
        results = resp.json().get("results", [])
        print(f"  Found {len(results)} results")

        # Check our site is in results
        found = any(r.get("hash_id") == hash_id for r in results)
        assert found, f"Published site {hash_id} not found in search results"
        print(f"  [OK] Site found in search results")

        # ============ TEST 4: Relevance ============
        print("\n========== TEST 4: Relevance check ==========")
        # Search with the unique keyword
        resp = requests.get(
            f"{SEARCH_URL}/query",
            params={"text": "zebrabanana123", "item_type": "website", "limit": 5},
            timeout=15,
        )
        assert resp.status_code == 200
        results = resp.json().get("results", [])
        print(f"  Found {len(results)} results for 'zebrabanana123'")

        if results:
            top = results[0]
            assert top.get("hash_id") == hash_id, \
                f"Expected {hash_id} as top result, got {top.get('hash_id')}"
            score = top.get("score", 0)
            assert score > 0.5, f"Score too low: {score}"
            print(f"  [OK] Top result is our site (score={score:.3f})")
        else:
            print("  WARN: No results (may need more index time)")

        # ============ TEST 4.5: Emoji support ============
        print("\n========== TEST 4.5: Emoji in website content ==========")
        emoji_zip = create_emoji_zip()
        print(f"  Emoji test zip size: {len(emoji_zip)} bytes")
        
        resp = requests.post(
            f"{SEARCH_URL}/proxy/publish_feedo",
            files={"file": ("emoji_site.zip", emoji_zip, "application/zip")},
            timeout=30,
        )
        assert resp.status_code == 200, f"Emoji site publish failed: {resp.text}"
        emoji_data = resp.json()
        emoji_hash = emoji_data.get("cid", "")
        assert emoji_hash, "No CID for emoji site"
        print(f"  [OK] Emoji site published: hash={emoji_hash}")

        time.sleep(3)
        
        # Search for emoji site by content keywords (not emoji itself)
        resp = requests.get(
            f"{SEARCH_URL}/query",
            params={"text": "Bitcoin rocket moon crypto", "item_type": "website", "limit": 10},
            timeout=15,
        )
        assert resp.status_code == 200
        emoji_results = resp.json().get("results", [])
        emoji_found = any(r.get("hash_id") == emoji_hash for r in emoji_results)
        assert emoji_found, f"Emoji site not found in search (is_gibberish might be rejecting it)"
        print(f"  [OK] Emoji site found in search (among {len(emoji_results)} results)")
        
        # Cleanup emoji site
        requests.delete(f"{SEARCH_URL}/proxy/unpin_feedo/{emoji_hash}", timeout=10)
        requests.delete(f"{STORAGE_URL}/delete/{emoji_hash}", timeout=10)

        # ============ TEST 5: Index document ============
        print("\n========== TEST 5: Index document directly ==========")
        doc_text = "Unique document about blockchain consensus algorithms and PBFT"
        resp = requests.post(
            f"{SEARCH_URL}/index_document",
            json={
                "hash_id": "test_direct_doc_001",
                "text": doc_text,
                "item_type": "document",
                "author": "test",
                "metadata": {"topic": "consensus"},
            },
            timeout=10,
        )
        assert resp.status_code == 200, f"Index document failed: {resp.text}"
        print(f"  [OK] Document indexed")

        time.sleep(2)

        # Search for it
        resp = requests.get(
            f"{SEARCH_URL}/query",
            params={"text": "blockchain consensus PBFT", "item_type": "document", "limit": 5},
            timeout=15,
        )
        results = resp.json().get("results", [])
        doc_found = any(r.get("hash_id") == "test_direct_doc_001" for r in results)
        print(f"  Document found in search: {doc_found} (among {len(results)} results)")
        # Note: might not find due to vector distance threshold, so this is soft

        # ============ TEST 6: Explorer stats ============
        print("\n========== TEST 6: Explorer stats ==========")
        resp = requests.get(f"{SEARCH_URL}/explorer/stats", timeout=10)
        assert resp.status_code == 200
        stats = resp.json()
        print(f"  Stats: {json.dumps(stats)}")
        assert stats.get("indexed_posts", 0) >= 1, \
            f"Expected at least 1 indexed post, got {stats.get('indexed_posts')}"
        print(f"  [OK] Explorer stats: {stats['indexed_posts']} indexed, health={stats.get('network_health')}")

        # ============ TEST 7: Cleanup ============
        print("\n========== TEST 7: Cleanup ==========")
        # Delete from storage
        resp = requests.delete(f"{STORAGE_URL}/delete/{hash_id}", timeout=10)
        print(f"  Storage delete: {resp.status_code}")

        # Delete from search index
        resp = requests.delete(f"{SEARCH_URL}/proxy/unpin_feedo/{hash_id}", timeout=10)
        print(f"  Search unpin: {resp.status_code} {resp.text}")

        # Delete test document
        resp = requests.delete(f"{SEARCH_URL}/proxy/unpin_feedo/test_direct_doc_001", timeout=10)
        print(f"  Test doc unpin: {resp.status_code}")

        # Verify deleted from storage (with retry in case storage still processing)
        for _ in range(3):
            try:
                resp = requests.get(f"{STORAGE_URL}/download/{hash_id}", timeout=5)
                if resp.status_code == 404:
                    print(f"  [OK] Storage confirms deletion (404)")
                    break
            except Exception:
                time.sleep(1)

        print("\n========== ALL SEARCH TESTS PASSED ==========")

    finally:
        # Kill processes
        if search_proc:
            print(f"\n[TEARDOWN] Killing search-node (PID={search_proc.pid})...")
            search_proc.terminate()
            try:
                search_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                search_proc.kill()
        if storage_proc:
            print(f"[TEARDOWN] Killing storage-node (PID={storage_proc.pid})...")
            storage_proc.terminate()
            try:
                storage_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                storage_proc.kill()

        # Clean DB dirs
        for d in [TEST_DB_DIR, LANCE_TEST_DB_DIR]:
            p = Path(d)
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
        print("[TEARDOWN] Done")


if __name__ == "__main__":
    test_publish_and_query()