import asyncio
import logging
import os
from typing import List

from .key_manager import load_or_create_peer_key
from .persistent_cache import PeerCache
from .discovery import LANDiscovery
from .gossipsub import GossipSub
from .replication import ReplicationManager
from .peer_registry import PeerRegistry
from .replay_cache import ReplayCache
from .reputation import ReputationManager
from .content_store import ContentStore
from .anti_entropy import AntiEntropyManager

logger = logging.getLogger("feedo_p2p")


class P2PManager:
    def __init__(self, *, bootstrap_nodes: List[str] | None = None):
        self.bootstrap_nodes = bootstrap_nodes or []
        self.peer_key_path = os.getenv("PEER_KEY_PATH", os.path.join(".", "peer_key.json"))
        self.peer_cache_path = os.getenv("PEER_CACHE_PATH", os.path.join(".", "peer_cache.json"))
        self.broadcast_port = int(os.getenv("FEEDO_BROADCAST_PORT", "9999"))
        self.gossip_port = int(os.getenv("FEEDO_GOSSIP_PORT", "10000"))
        self.replication_factor = int(os.getenv("FEEDO_REPLICATION_FACTOR", "3"))

        self.key = load_or_create_peer_key(self.peer_key_path)
        self.peer_id = self.key["peer_id"]
        self.cache = PeerCache(self.peer_cache_path)
        self.peer_registry = PeerRegistry(os.getenv('FEEDO_PEER_REGISTRY', os.path.join('.', 'peer_registry.json')))
        self.reputation = ReputationManager(os.getenv('FEEDO_REPUTATION_STORE', os.path.join('.', 'reputation.json')))
        self.replay_cache = ReplayCache(os.getenv('FEEDO_REPLAY_CACHE', os.path.join('.', 'replay_cache.json')))

        self.discovery = LANDiscovery(self.peer_id, port=self.broadcast_port, on_peer=self._on_peer_discovered)
        self.gossip = GossipSub(self.peer_id, port=self.gossip_port, on_message=self._on_gossip)
        self.content_store = ContentStore(os.getenv("FEEDO_CONTENT_STORE", os.path.join(".", "content_store.json")))
        self.replication = ReplicationManager(self.cache, replication_factor=self.replication_factor, content_store=self.content_store)
        self.anti_entropy = AntiEntropyManager(self.content_store, self.gossip, self.cache, interval=int(os.getenv("FEEDO_ANTI_INTERVAL", "60")))

        self._tasks = []
        self._running = False

    async def start(self):
        logger.info("Starting P2PManager peer_id=%s", self.peer_id)
        self._running = True
        await self.discovery.start()
        await self.gossip.start()
        await self.replication.start()
        await self.anti_entropy.start()

        # Bootstrap to configured nodes
        asyncio.create_task(self._bootstrap())

        # periodic dialer
        self._tasks.append(asyncio.create_task(self._periodic_dial()))
        # watcher for local shard_dir to proactively replicate
        try:
            self._tasks.append(asyncio.create_task(self._shard_watcher_loop()))
        except Exception:
            pass

    async def _shard_watcher_loop(self):
        last_seen = set()
        while self._running:
            try:
                files = []
                for name in os.listdir(self.content_store.shard_dir):
                    full = os.path.join(self.content_store.shard_dir, name)
                    if os.path.isfile(full):
                        files.append((name, os.path.getmtime(full)))
                # detect new
                current = {n for n, _ in files}
                new = current - last_seen
                for n in new:
                    shard_id = n
                    # call replication ensure
                    path = os.path.join(self.content_store.shard_dir, n)
                    try:
                        with open(path, 'rb') as f:
                            data = f.read()
                        await self.replication.ensure_replication(shard_id, data, self.cache.get_best_peers(limit=10))
                    except Exception:
                        pass
                last_seen = current
            except Exception:
                pass
            await asyncio.sleep(10)

    async def stop(self):
        logger.info("Stopping P2PManager")
        self._running = False
        try:
            await self.discovery.stop()
        except Exception:
            pass
        try:
            await self.gossip.stop()
        except Exception:
            pass
        try:
            await self.replication.stop()
        except Exception:
            pass
        try:
            await self.anti_entropy.stop()
        except Exception:
            pass
        for t in self._tasks:
            t.cancel()
            try:
                await t
            except Exception:
                pass

    async def _bootstrap(self):
        # Try bootstrap nodes: add to cache and try a quick connect
        for b in self.bootstrap_nodes:
            try:
                # accept forms like host:port or http(s) urls
                addr = b
                self.cache.add_or_update(addr, [addr], score=1.0)
            except Exception:
                pass

    def _on_peer_discovered(self, peer_info: dict):
        # peer_info: {peer_id, addr}
        try:
            self.cache.add_or_update(peer_info["peer_id"], [peer_info["addr"]], score=1.0)
        except Exception:
            pass

    def _on_gossip(self, msg: dict):
        # dispatch gossip messages: announce + anti-entropy/fetch
        try:
            topic = msg.get("topic")
            pid = msg.get("peer_id")
            payload = msg.get("payload") or {}

            if topic == "announce":
                addrs = []
                if isinstance(payload, dict):
                    addrs = payload.get("addrs")
                    pubkey = payload.get("pubkey_hex")
                    is_supernode = payload.get("is_supernode", False)
                    if pubkey and hasattr(self, "peer_registry") and self.peer_registry:
                        self.peer_registry.register(pid, pubkey, is_supernode=is_supernode)
                self.cache.add_or_update(pid, addrs or [], score=1.0)

            # forward to anti-entropy manager for handling of anti_entropy_summary, fetch_request, fetch_response
            try:
                if hasattr(self, "anti_entropy") and self.anti_entropy is not None:
                    self.anti_entropy.handle_message(msg)
            except Exception:
                pass

        except Exception:
            pass

    async def _periodic_dial(self):
        """Periodically attempt to connect to best peers from cache."""
        while self._running:
            peers = self.cache.get_best_peers(limit=10)
            for p in peers:
                for a in p.get("addrs", []):
                    try:
                        host, port = a.split(":") if ":" in a else (a, None)
                        if port is None:
                            port = 80
                        port = int(port)
                        
                        pubkey = self.key.get("pubkey_hex")
                        if pubkey:
                            import aiohttp
                            url = f"http://{host}:{port}/internal/p2p/register_peer"
                            async with aiohttp.ClientSession() as session:
                                try:
                                    is_sn = os.getenv("IS_SUPERNODE", "false").lower() == "true"
                                    await session.post(url, json={"peer_id": self.peer_id, "pubkey_hex": pubkey, "is_supernode": is_sn}, timeout=5)
                                except Exception:
                                    pass

                        reader, writer = await asyncio.open_connection(host, port)
                        writer.close()
                        await writer.wait_closed()
                        self.cache.mark_success(p["peer_id"])
                    except Exception:
                        self.cache.mark_failure(p.get("peer_id", ""))
            await asyncio.sleep(15)

    async def announce(self):
        # publish an announce message with local addresses if any
        is_supernode = os.getenv("IS_SUPERNODE", "false").lower() == "true"
        payload = {"addrs": [], "pubkey_hex": self.key.get("pubkey_hex"), "is_supernode": is_supernode}
        try:
            await self.gossip.publish("announce", payload)
        except Exception:
            pass
