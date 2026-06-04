import asyncio
import json
import socket
from typing import Callable

DEFAULT_PORT = 10000


class GossipSub:
    """Very small 'gossipsub' over UDP broadcast for peer announce messages.

    Peers send topic messages as JSON: {"topic": "announce", "peer_id":..., "payload": {...}}
    Listeners receive and can act on them.
    """

    def __init__(self, peer_id: str, port: int = DEFAULT_PORT, on_message: Callable[[dict], None] = None):
        self.peer_id = peer_id
        self.port = port
        self.on_message = on_message
        self._task = None
        self._running = False

    async def start(self):
        loop = asyncio.get_running_loop()
        self._running = True
        listen = loop.create_datagram_endpoint(
            lambda: _GossipUDPListener(self._handle),
            local_addr=("0.0.0.0", self.port),
        )
        self._transport, _ = await listen
        self._task = asyncio.create_task(self._periodic_ping())

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

    async def publish(self, topic: str, payload: dict):
        msg = {"topic": topic, "peer_id": self.peer_id, "payload": payload}
        data = json.dumps(msg).encode("utf-8")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        try:
            sock.sendto(data, ("255.255.255.255", self.port))
        except Exception:
            pass

    async def _periodic_ping(self):
        while self._running:
            try:
                await self.publish("announce", {"status": "online"})
            except Exception:
                pass
            await asyncio.sleep(10)

    def _handle(self, data: bytes, addr):
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("peer_id") == self.peer_id:
            return
        if self.on_message:
            try:
                self.on_message(msg)
            except Exception:
                pass


class _GossipUDPListener(asyncio.DatagramProtocol):
    def __init__(self, callback):
        self._callback = callback

    def datagram_received(self, data, addr):
        try:
            self._callback(data, addr)
        except Exception:
            pass
