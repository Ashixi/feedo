import pytest
import httpx

@pytest.mark.anyio
class TestFeedoFrontendFlow:

    async def test_content_lifecycle_and_status(self, api_client):

        payload = {
            "author_did": "did:feedo:12345",
            "protobuf_bytes": "0a100802120c48656c6c6f20466565646f", 
            "signature": "mock_sig_abcdef"
        }
        
        publish_res = await api_client.post("/content/publish", json=payload)
        assert publish_res.status_code == 200, "Не вдалося опублікувати контент"
        
        data = publish_res.json()
        assert "hash_id" in data
        hash_id = data["hash_id"]
        
        status_res = await api_client.get(f"/content/status/{hash_id}")
        assert status_res.status_code == 200
        
        status_data = status_res.json()
        assert "status" in status_data
        assert status_data["status"] in ["mempool", "committed", "pbft_voting"]

        content_res = await api_client.get(f"/content/{hash_id}")
        assert content_res.status_code == 200
        assert content_res.json()["hash_id"] == hash_id

    async def test_bookmark_and_graph_topology(self, api_client):

        target_post_hash = "sha256_mocked_post_hash_00000000000000000"

        edge_payload = {
            "source_id": "did:feedo:user_wallet_address",
            "target_id": target_post_hash,
            "edge_type": "bookmark",
            "timestamp": 1718025600
        }
        
        edge_res = await api_client.post("/graph/edge", json=edge_payload)
        assert edge_res.status_code == 201 or edge_res.status_code == 200
        
        outbound_res = await api_client.get(f"/graph/edges/outbound/did:feedo:user_wallet_address")
        assert outbound_res.status_code == 200
        
        edges = outbound_res.json().get("edges", [])
        assert any(e["target_id"] == target_post_hash and e["edge_type"] == "bookmark" for e in edges)

    async def test_crdt_dynamic_state(self, api_client):

        object_id = "likes_counter_post_99"

        mutate_payload = {
            "object_id": object_id,
            "operation": "add",
            "value": "user_did_456",
            "clock": 1 
        }
        
        mutate_res = await api_client.post("/crdt/mutate", json=mutate_payload)
        assert mutate_res.status_code == 200

        state_res = await api_client.get(f"/crdt/{object_id}")
        assert state_res.status_code == 200
        
        state_data = state_res.json()
        assert "state" in state_data
        assert "user_did_456" in state_data["state"]

    async def test_node_health_and_metrics(self, api_client):

        health_res = await api_client.get("/node/health")
        assert health_res.status_code == 200
        assert health_res.json().get("status") == "healthy"
        
        metrics_res = await api_client.get("/node/metrics")
        assert metrics_res.status_code == 200
        metrics = metrics_res.json()

        assert "connected_peers" in metrics
        assert "mempool_size" in metrics
        assert "pbft_latency" in metrics
