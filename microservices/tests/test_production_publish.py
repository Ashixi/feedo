#!/usr/bin/env python3
"""
Production Publish Test -- hits api.feedo.ink exactly like the Flutter browser does.

Tests the FULL domain registration pipeline against production servers:
  1. Register DID
  2. Publish placeholder ZIP via search-node proxy (/proxy/publish_feedo)
  3. Register name on consensus
  4. Update CID on consensus
  5. Resolve domain
  6. Cleanup

Run:
    cd microservices\tests
    python test_production_publish.py
"""

import json
import time
import zipfile
import tempfile
import shutil
import os
import requests
from eth_account import Account
from eth_account.messages import encode_defunct

# --- Config ---
# Matches ApiClient.gateways in browser/lib/core/api_client.dart
PROXY_URL = "https://api2.feedo.ink"
CONSENSUS_URL = f"{PROXY_URL}/consensus"

# --- Helpers ---


def make_placeholder_zip(domain, did):
    """Create a placeholder HTML zip -- exactly what publish_screen.dart does."""
    html = f"""<!DOCTYPE html>
<html>
<head><title>{domain}</title></head>
<body style="font-family: sans-serif; text-align: center; margin-top: 20%; background-color: #f9fafb;">
  <h1 style="color: #111827;">Domain {domain}</h1>
  <p style="color: #4b5563;">This domain is owned by DID:<br><code style="background: #e5e7eb; padding: 4px 8px; border-radius: 4px; margin-top: 10px; display: inline-block;">{did}</code></p>
  <p style="color: #9ca3af; margin-top: 40px;"><em>Powered by Feedo Network</em></p>
</body>
</html>"""

    tmpdir = tempfile.mkdtemp()
    index_path = os.path.join(tmpdir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)

    zip_path = os.path.join(tmpdir, "site.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(index_path, "index.html")

    with open(zip_path, "rb") as f:
        data = f.read()

    shutil.rmtree(tmpdir)
    return data


def test_production_pipeline():
    print("=" * 60)
    print("PRODUCTION PUBLISH TEST")
    print(f"  Proxy:      {PROXY_URL}")
    print(f"  Consensus:  {CONSENSUS_URL}")
    print("=" * 60)

    # Generate a test wallet (same as full_cycle_test.py)
    priv_hex = "11" * 32
    acct = Account.from_key(priv_hex)
    pub_hex = acct.address  # "0x..." format
    domain_name = f"test-{int(time.time())}.feedo"

    # ========== STEP 1: Register DID ==========
    print("\n[STEP 1] Register DID...")
    resp = requests.post(
        f"{CONSENSUS_URL}/did/register",
        json={"public_key": pub_hex},
        timeout=15,
    )
    print(f"  Status: {resp.status_code}")
    print(f"  Body:   {resp.text}")
    if resp.status_code != 200:
        print("  [FAIL] DID registration FAILED -- aborting")
        return

    did = resp.json().get("did", "")
    print(f"  [OK] DID: {did}")


    # ========== STEP 2: Publish placeholder ZIP ==========
    print("\n[STEP 2] Publish placeholder ZIP via search-node proxy...")
    zip_bytes = make_placeholder_zip(domain_name, did)
    print(f"  ZIP size: {len(zip_bytes)} bytes")

    # Try with explicit content_type like the browser now does
    print("  --- Attempt with explicit application/zip content-type ---")
    resp = requests.post(
        f"{PROXY_URL}/proxy/publish_feedo",
        files={"file": ("site.zip", zip_bytes, "application/zip")},
        timeout=30,
    )
    print(f"  Status: {resp.status_code}")
    print(f"  Headers: {dict(resp.headers)}")
    print(f"  Body:    {resp.text[:500]}")

    if resp.status_code != 200:
        print("\n  --- Attempt WITHOUT explicit content-type (old browser behavior) ---")
        resp2 = requests.post(
            f"{PROXY_URL}/proxy/publish_feedo",
            files={"file": ("site.zip", zip_bytes)},
            timeout=30,
        )
        print(f"  Status: {resp2.status_code}")
        print(f"  Headers: {dict(resp2.headers)}")
        print(f"  Body:    {resp2.text[:500]}")

        print("\n  --- Attempt with raw binary body (no multipart) ---")
        resp3 = requests.post(
            f"{PROXY_URL}/proxy/publish_feedo",
            data=zip_bytes,
            headers={"Content-Type": "application/zip"},
            timeout=30,
        )
        print(f"  Status: {resp3.status_code}")
        print(f"  Body:    {resp3.text[:500]}")

        # Also try direct storage upload
        print("\n  --- Attempt direct upload to storage via proxy upload endpoint ---")
        resp4 = requests.post(
            f"{PROXY_URL}/upload",
            files={"file": ("site.zip", zip_bytes, "application/zip")},
            timeout=30,
        )
        print(f"  Status: {resp4.status_code}")
        print(f"  Body:    {resp4.text[:500]}")

        print("  [FAIL] Publish FAILED -- aborting")
        return

    data = resp.json()
    cid = data.get("cid", "")
    if not cid:
        print("  [FAIL] No CID in response -- aborting")
        print(f"  Full response: {json.dumps(data, indent=2)}")
        return

    if len(cid) != 64:
        print(f"  [WARN] CID length is {len(cid)}, expected 64 (SHA256)")
        print(f"  CID: {cid}")

    print(f"  [OK] Published! CID: {cid}")
    print(f"  Title: {data.get('title', 'N/A')}")


    # ========== STEP 3: Register name on consensus ==========
    print("\n[STEP 3] Register name on consensus...")
    name_payload = f"{domain_name}{did}"
    msg = encode_defunct(text=name_payload)
    sig_obj = acct.sign_message(msg)
    sig_hex = "0x" + sig_obj.signature.hex()

    print(f"  Name:      {domain_name}")
    print(f"  DID:       {did}")
    print(f"  Pub key:   {pub_hex}")
    print(f"  Sig len:   {len(sig_hex)} chars (including 0x)")
    print(f"  Sig first: {sig_hex[:30]}...")

    resp = requests.post(
        f"{CONSENSUS_URL}/name/register",
        json={
            "name": domain_name,
            "did": did,
            "public_key": pub_hex,
            "signature": sig_hex,
        },
        timeout=15,
    )
    print(f"  Status: {resp.status_code}")
    print(f"  Body:   {resp.text}")
    if resp.status_code != 200 or not resp.json().get("success"):
        print("  [FAIL] Name registration FAILED")
        return
    print("  [OK] Name registered!")


    # ========== STEP 4: Bind CID to domain ==========
    print("\n[STEP 4] Bind CID to domain...")
    cid_payload = f"{domain_name}{cid}"
    cid_msg = encode_defunct(text=cid_payload)
    cid_sig_obj = acct.sign_message(cid_msg)
    cid_sig_hex = "0x" + cid_sig_obj.signature.hex()

    print(f"  CID:       {cid}")
    print(f"  Sig first: {cid_sig_hex[:30]}...")

    resp = requests.post(
        f"{CONSENSUS_URL}/name/update_cid",
        json={
            "name": domain_name,
            "cid": cid,
            "signature": cid_sig_hex,
            "gateways": [],
        },
        timeout=15,
    )
    print(f"  Status: {resp.status_code}")
    print(f"  Body:   {resp.text}")
    if resp.status_code != 200 or not resp.json().get("success"):
        print("  [FAIL] CID binding FAILED")
        return
    print("  [OK] CID bound!")


    # ========== STEP 5: Resolve domain ==========
    print("\n[STEP 5] Resolve domain...")
    time.sleep(2)
    resp = requests.get(f"{CONSENSUS_URL}/resolve/{domain_name}", timeout=10)
    print(f"  Status: {resp.status_code}")
    print(f"  Body:   {resp.text}")
    data = resp.json() if resp.status_code == 200 else {}
    if data.get("cid") == cid:
        print(f"  [OK] Domain resolves correctly to {cid}")
    else:
        print(f"  [WARN] CID mismatch: expected {cid}, got {data.get('cid')}")


    # ========== STEP 6: Cleanup ==========
    print("\n[STEP 6] Cleanup...")
    resp = requests.delete(f"{PROXY_URL}/proxy/unpin_feedo/{cid}", timeout=10)
    print(f"  Unpin: {resp.status_code} {resp.text}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    test_production_pipeline()