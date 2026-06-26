import pytest
import time
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from main import app
from auth_deps import rate_limiter
from models import ApiKeyRole

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_rate_limiter():
    # Clear tokens before each test
    rate_limiter.buckets.clear()
    yield

def test_health_check():
    response = client.get("/internal/vector/health")
    assert response.status_code == 200
    assert "status" in response.json()

def test_anonymous_rate_limit():
    # Assume EXPOSE_VECTOR_API is True in test env
    # Mock EXPOSE_VECTOR_API if needed
    with patch("main.EXPOSE_VECTOR_API", True):
        # 10 reqs allowed for anon
        for _ in range(10):
            response = client.get("/internal/vector/recent?limit=1")
            assert response.status_code in (200, 404, 500) # depending on DB state, but not 429
            
        # 11th should be 429
        response = client.get("/internal/vector/recent?limit=1")
        assert response.status_code == 429

def test_batch_query_forbidden_for_anon():
    with patch("main.EXPOSE_VECTOR_API", True):
        response = client.post("/internal/vector/batch_query", json={"vectors": [[0.1]*1024], "k": 5})
        assert response.status_code == 403
        assert "not allowed for anonymous" in response.json()["detail"]

def test_invalid_api_key():
    with patch("main.EXPOSE_VECTOR_API", True):
        response = client.get("/internal/vector/recent?limit=1", headers={"x-vector-api-key": "invalid_key"})
        assert response.status_code == 401

@pytest.mark.asyncio
async def test_aggregator_circuit_breaker():
    from aggregator import AggregatorClient
    client = AggregatorClient(timeout=0.1)
    
    # Force 5 failures
    for _ in range(5):
        await client.fetch_recent_hash_ids("http://invalid.local:1234")
        
    assert client.circuit_breaker.is_open("http://invalid.local:1234") == True
    
    # Should short circuit
    res = await client.fetch_recent_hash_ids("http://invalid.local:1234")
    assert res == []
