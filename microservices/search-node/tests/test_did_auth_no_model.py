"""
Test DID auth gate in search-node WITHOUT loading the neural network.

Strategy: We inject fake modules into sys.modules BEFORE importing main.py.
This means torch/transformers/sentence-transformers are NEVER touched.
Zero internet required.
"""

import sys
import time
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

# ============================================================
# 1. MOCK ALL HEAVY MODULES BEFORE ANY IMPORT OF main.py
# ============================================================

# Mock vector_service entirely - no model loading
mock_vector_brain = MagicMock()
mock_vector_brain.encode = MagicMock(return_value=[0.1] * 384)
mock_vector_brain.search = AsyncMock(return_value=[])
mock_vector_brain.index = AsyncMock(return_value=True)

mock_vector_service_module = MagicMock()
mock_vector_service_module.VectorBrain = MagicMock(return_value=mock_vector_brain)
sys.modules['vector_service'] = mock_vector_service_module

# Mock p2p, crawler, storage_adapters (all potentially heavy)
sys.modules['p2p'] = MagicMock()
sys.modules['crawler'] = MagicMock()
sys.modules['storage_adapters'] = MagicMock()
sys.modules['lancedb'] = MagicMock()
sys.modules['sentence_transformers'] = MagicMock()
sys.modules['torch'] = MagicMock()
sys.modules['bs4'] = MagicMock()

# ============================================================
# 2. NOW we can safely import the auth module (pure crypto)
# ============================================================
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

from auth import verify_feedo_auth

# ============================================================
# 3. HELPERS
# ============================================================

CONSENSUS_NODE_URL = "http://95.111.245.68:3000"

def make_signed_headers(private_key: str, method: str, path: str) -> dict:
    """Generate valid X-Feedo-* auth headers for a request."""
    account = Account.from_key(private_key)
    did = f"did:feedo:{account.address}"
    timestamp = str(int(time.time() * 1000))
    payload = f"FeedoAction:{method}:{path}:{timestamp}"
    message = encode_defunct(text=payload)
    signed = Account.sign_message(message, private_key=private_key)
    return {
        "X-Feedo-DID": did,
        "X-Feedo-Timestamp": timestamp,
        "X-Feedo-Signature": signed.signature.hex(),
    }


class MockRequest:
    """Minimal fake FastAPI Request for testing auth."""
    def __init__(self, method: str, path: str, headers: dict):
        self.method = method
        self.headers = headers
        self.url = type("URL", (), {"path": path})()


# ============================================================
# 4. TESTS
# ============================================================

@pytest.mark.asyncio
async def test_missing_headers_returns_401():
    """Request without any auth headers must be rejected."""
    req = MockRequest("GET", "/search", headers={})
    result = await verify_feedo_auth(req)
    assert result is not None
    assert result.status_code == 401
    print("✅ Missing headers → 401 UNAUTHORIZED (correct)")


@pytest.mark.asyncio
async def test_invalid_signature_returns_401():
    """Request with a wrong/garbage signature must be rejected."""
    req = MockRequest("GET", "/search", headers={
        "X-Feedo-DID": "did:feedo:0x1234567890123456789012345678901234567890",
        "X-Feedo-Timestamp": str(int(time.time() * 1000)),
        "X-Feedo-Signature": "0x" + "ab" * 65,  # garbage signature
    })
    result = await verify_feedo_auth(req)
    assert result is not None
    assert result.status_code == 401
    print("✅ Invalid signature → 401 UNAUTHORIZED (correct)")


@pytest.mark.asyncio
async def test_expired_timestamp_returns_401():
    """Request with timestamp older than 5 minutes must be rejected (replay attack prevention)."""
    private_key = Account.create().key.hex()
    account = Account.from_key(private_key)
    did = f"did:feedo:{account.address}"

    # Timestamp 10 minutes in the past
    old_timestamp = str(int(time.time() * 1000) - 10 * 60 * 1000)
    payload = f"FeedoAction:GET:/search:{old_timestamp}"
    message = encode_defunct(text=payload)
    signed = Account.sign_message(message, private_key=private_key)

    req = MockRequest("GET", "/search", headers={
        "X-Feedo-DID": did,
        "X-Feedo-Timestamp": old_timestamp,
        "X-Feedo-Signature": signed.signature.hex(),
    })
    result = await verify_feedo_auth(req)
    assert result is not None
    assert result.status_code == 401
    print("✅ Expired timestamp → 401 UNAUTHORIZED (replay attack blocked)")


@pytest.mark.asyncio
async def test_public_endpoint_skips_auth():
    """/explorer/stats and /p2p/ routes must bypass DID auth."""
    req_stats = MockRequest("GET", "/explorer/stats", headers={})
    result = await verify_feedo_auth(req_stats)
    assert result is None
    print("✅ /explorer/stats → auth skipped (correct)")

    req_p2p = MockRequest("GET", "/p2p/peers", headers={})
    result = await verify_feedo_auth(req_p2p)
    assert result is None
    print("✅ /p2p/peers → auth skipped (correct)")


@pytest.mark.asyncio
async def test_valid_did_passes_auth():
    """
    Full happy path: valid signature + mocked Consensus Node saying DID is registered.
    100% offline - no real server needed.
    """
    private_key = Account.create().key.hex()
    headers = make_signed_headers(private_key, "GET", "/search")
    req = MockRequest("GET", "/search", headers=headers)

    # Mock the Consensus Node HTTP response → 200 OK (DID is registered)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={"balance": 100})

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await verify_feedo_auth(req)

    assert result is None  # None = auth passed!
    print("✅ Valid DID + mocked consensus → AUTH PASSED (correct)")


@pytest.mark.asyncio
async def test_unregistered_did_rejected_by_consensus():
    """
    DID has valid signature but Consensus Node says it's not registered → 401.
    100% offline.
    """
    private_key = Account.create().key.hex()
    headers = make_signed_headers(private_key, "GET", "/search")
    req = MockRequest("GET", "/search", headers=headers)

    # Mock the Consensus Node HTTP response → 404 (DID not registered)
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.json = MagicMock(return_value=None)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await verify_feedo_auth(req)

    assert result is not None
    assert result.status_code == 401
    print("✅ Valid signature but unregistered DID → 401 REJECTED by consensus (correct)")

