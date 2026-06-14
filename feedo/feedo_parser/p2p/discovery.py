import asyncio
import json
import socket
import sys
from typing import Callable


DEFAULT_PORT = 9999


class LANDiscovery:
    """Simple LAN discovery using UDP broadcast.

    Sends and receives small JSON messages announcing a peer's presence.
    This is intentionally lightweight and works across OSes that allow
    UDP broadcasts on the local network.
    """

    def __init__(self, peer_id: str, port: int = DEFAULT_PORT, on_peer=None):
        self.peer_id = peer_id
        self.port = port
        self.on_peer: Callable[[dict], None] = on_peer
        self._task = None
        self._running = False

    async def start(self):
        loop = asyncio.get_running_loop()
        self._running = True
        listen = loop.create_datagram_endpoint(
            lambda: _UDPListener(self._handle_message),
            local_addr=("0.0.0.0", self.port),
        )
        transport, protocol = await listen

        # Start periodic broadcaster
        self._task = asyncio.create_task(self._broadcaster())
        self._transport = transport

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
        if getattr(self, "_transport", None):
            self._transport.close()

    async def _broadcaster(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        msg = {"type": "feedo_discover", "peer_id": self.peer_id}
        while self._running:
            try:
                data = json.dumps(msg).encode("utf-8")
                # send to broadcast address
                sock.sendto(data, ("255.255.255.255", self.port))
            except Exception:
                pass
            await asyncio.sleep(5)

    def _handle_message(self, data: bytes, addr):
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("peer_id") == self.peer_id:
            return
        if self.on_peer:
            peer_info = {"peer_id": msg.get("peer_id"), "addr": f"{addr[0]}:{addr[1]}"}
            try:
                self.on_peer(peer_info)
            except Exception:
                pass


class _UDPListener(asyncio.DatagramProtocol):
    def __init__(self, callback):
        self._callback = callback

    def datagram_received(self, data, addr):
        try:
            self._callback(data, addr)
        except Exception:
            pass
