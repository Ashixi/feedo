import pytest
import respx
import httpx
import asyncio
from feedo.router import NodeRouter

@pytest.mark.asyncio
async def test_find_fastest_node_all_up():
    router = NodeRouter(search_seeds=["http://node1", "http://node2"])
    
    with respx.mock:
        # Mock node1 to respond instantly
        route1 = respx.get("http://node1/explorer/stats").mock(return_value=httpx.Response(200, json={}))
        
        # Mock node2 to be slightly delayed (not natively easy in respx without custom side effects, 
        # so we just let them both return and asyncio.wait handles whichever resolves first - since route1 is first, 
        # or we can mock one to raise a timeout and the other to succeed)
        
        route2 = respx.get("http://node2/explorer/stats").mock(side_effect=httpx.TimeoutException("Timeout"))

        active_node = await router.get_search_node()
        assert active_node == "http://node1"

@pytest.mark.asyncio
async def test_fallback_when_one_down():
    router = NodeRouter(search_seeds=["http://node1", "http://node2"])
    
    with respx.mock:
        # node1 fails
        respx.get("http://node1/explorer/stats").mock(return_value=httpx.Response(500))
        # node2 succeeds
        respx.get("http://node2/explorer/stats").mock(return_value=httpx.Response(200, json={}))

        active_node = await router.get_search_node()
        assert active_node == "http://node2"

@pytest.mark.asyncio
async def test_fallback_when_all_down():
    router = NodeRouter(search_seeds=["http://node1", "http://node2"])
    
    with respx.mock:
        respx.get("http://node1/explorer/stats").mock(side_effect=httpx.ConnectError("Down"))
        respx.get("http://node2/explorer/stats").mock(side_effect=httpx.ConnectError("Down"))

        active_node = await router.get_search_node()
        # Should fallback to the first node if all fail
        assert active_node == "http://node1"
