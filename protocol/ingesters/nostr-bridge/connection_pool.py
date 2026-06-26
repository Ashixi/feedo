import asyncio
import logging
import websockets
from typing import Dict, Optional

logger = logging.getLogger("connection_pool")

class RelayConnectionPool:
    """
    Manages WebSocket connections to hundreds of Nostr relays simultaneously.
    Provides connection reuse, retry backoff, and graceful disconnection.
    """
    def __init__(self, max_connections: int = 500):
        self.max_connections = max_connections
        self.connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.locks: Dict[str, asyncio.Lock] = {}
        
    async def get_connection(self, relay_url: str) -> Optional[websockets.WebSocketClientProtocol]:
        """Get an existing connection or establish a new one."""
        if relay_url not in self.locks:
            self.locks[relay_url] = asyncio.Lock()
            
        async with self.locks[relay_url]:
            if relay_url in self.connections:
                ws = self.connections[relay_url]
                is_open = ws.open if hasattr(ws, 'open') else not getattr(ws, 'closed', True)
                if is_open:
                    return ws
                else:
                    # Cleanup closed connection
                    del self.connections[relay_url]
                    
            if len(self.connections) >= self.max_connections:
                logger.warning(f"Connection pool limit reached ({self.max_connections}). Cannot connect to {relay_url}")
                return None
                
            try:
                # Open new connection
                ws = await websockets.connect(relay_url, open_timeout=15, close_timeout=5)
                self.connections[relay_url] = ws
                return ws
            except Exception as e:
                logger.error(f"Failed to connect to relay {relay_url}: {e}")
                return None

    async def close_all(self):
        """Close all active websocket connections."""
        logger.info(f"Closing {len(self.connections)} active relay connections...")
        for url, ws in list(self.connections.items()):
            is_open = ws.open if hasattr(ws, 'open') else not getattr(ws, 'closed', True)
            if is_open:
                try:
                    await ws.close()
                except Exception as e:
                    logger.debug(f"Error closing {url}: {e}")
        self.connections.clear()
