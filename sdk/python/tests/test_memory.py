import pytest
from unittest.mock import MagicMock, patch
from feedo.memory import FeedoMemory

@pytest.fixture
def mock_memory():
    with patch("feedo.memory.FeedoClient") as mock_client_cls:
        with patch("feedo.memory._resolve_did", return_value="did:feedo:dummy"):
            mock_client = mock_client_cls.return_value
            # Mock _run to just return the coro/mock directly
            memory = FeedoMemory(usage_key="0x123")
            memory._run = MagicMock(side_effect=lambda x: x)
            memory.client = mock_client
            return memory

def test_add(mock_memory):
    mock_memory.add_long = MagicMock(return_value="mem_123")
    res = mock_memory.add("Hello World", metadata={"topic": "test"})
    
    mock_memory.add_long.assert_called_once_with("Hello World", {"topic": "test"})
    assert res == "mem_123"

def test_search(mock_memory):
    mock_memory.search_long = MagicMock(return_value=[{"id": "mem_123", "text": "Hello World"}])
    res = mock_memory.search("Hello", limit=10)
    
    mock_memory.search_long.assert_called_once_with("Hello", 10)
    assert len(res) == 1
    assert res[0]["text"] == "Hello World"

def test_delete(mock_memory):
    mock_memory.delete("mem_123")
    mock_memory.client.search.unpin.assert_called_once_with("mem_123")
    mock_memory._run.assert_called_once()

def test_update(mock_memory):
    mock_memory.delete = MagicMock()
    mock_memory.add = MagicMock(return_value="mem_456")
    
    res = mock_memory.update("mem_123", "New World", metadata={"topic": "updated"})
    
    mock_memory.delete.assert_called_once_with("mem_123")
    mock_memory.add.assert_called_once_with("New World", {"topic": "updated"})
    assert res == "mem_456"
