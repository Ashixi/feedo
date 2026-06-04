import asyncio
import logging
import time
import os
from typing import List
import aiohttp
import json
import uuid

from .replication_metadata import ReplicationMetadata
from .metrics import REPLICA_REPAIRS_FAILED, REPLICA_REPAIRS_SUCCEEDED

logger = logging.getLogger("feedo_p2p_replication")


class ReplicationManager:
    def __init__(self, cache, replication_factor: int = 3, metadata_path: str = None, content_store=None):
        self.cache = cache
        self.replication_factor = replication_factor
        self._task = None
        self._running = False
        self.metadata = ReplicationMetadata(metadata_path or ".replication_metadata.json")
        self.content_store = content_store

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._repair_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass

    async def _repair_loop(self):
        while self._running:
            try:
                await self._repair_once()
            except Exception as e:
                logger.exception("Repair loop error: %s", e)
            await asyncio.sleep(30)

    async def _repair_once(self):
        # For each known shard in metadata, ensure desired replicas exist
        # If below desired, attempt to push to best peers from cache
        for shard_id, info in list(self.metadata._data.items()):
            desired = info.get("desired", self.replication_factor)
            current = len(info.get("peers", {}))
            if current < desired:
                needed = desired - current
                candidates = self.cache.get_best_peers(limit=20)
                # filter out peers that already have it
                existing = set(info.get("peers", {}).keys())
                attempts = 0
                for c in candidates:
                    pid = c.get("peer_id")
                    if pid in existing:
                        continue
                    addrs = c.get("addrs", [])
                    for a in addrs:
                        if attempts >= needed:
                            break
                        ok = await self._push_shard_to_addr(shard_id, a)
                        if ok:
                            self.metadata.note_replica(shard_id, pid)
                            attempts += 1
                if attempts == 0:
                    REPLICA_REPAIRS_FAILED.inc()
                else:
                    REPLICA_REPAIRS_SUCCEEDED.inc(attempts)

    async def _push_shard_to_addr(self, shard_id: str, addr: str) -> bool:
        # addr is like host:port
        try:
            host, port = addr.split(":") if ":" in addr else (addr, "80")
            url = f"http://{host}:{int(port)}/internal/p2p/receive_shard"
            # load shard bytes from provided content_store if available
            file_bytes = None
            if self.content_store is not None and self.content_store.has_file(shard_id):
                p = self.content_store.get_file_path(shard_id)
                try:
                    with open(p, 'rb') as f:
                        file_bytes = f.read()
                except Exception:
                    file_bytes = None

            headers = {}
            shared = ''
            try:
                shared = os.getenv('FEEDO_P2P_SHARED_SECRET', '')
            except Exception:
                shared = ''

            async with aiohttp.ClientSession() as session:
                if file_bytes is not None:
                    # send multipart/form-data: metadata + file
                    data = aiohttp.FormData()
                    metadata = {"shard_id": shard_id, "checksum": __import__('hashlib').sha256(file_bytes).hexdigest(), "size": len(file_bytes)}
                    # compute hmac over canonical
                    from .security import make_hmac, sign_ed25519
                    
                    ts = str(int(time.time()))
                    nonce = uuid.uuid4().hex
                    peer_id = None
                    try:
                        # Find peer_id and privkey if available globally
                        # Usually manager sets PEER_ID env or we load from peer_key.json
                        from .key_manager import load_or_create_peer_key
                        pk_path = os.getenv("PEER_KEY_PATH", os.path.join(".", "peer_key.json"))
                        key_data = load_or_create_peer_key(pk_path)
                        peer_id = key_data.get("peer_id")
                        metadata["origin_peer_id"] = peer_id
                        metadata["ts"] = ts
                        metadata["nonce"] = nonce
                        
                        msg = f"{shard_id}:{metadata['checksum']}:{metadata['size']}:{ts}:{peer_id or ''}"
                        
                        privkey = key_data.get("privkey_hex")
                        if privkey:
                            sig = sign_ed25519(privkey, msg.encode('utf-8'))
                            if sig:
                                metadata["signature"] = sig
                    except Exception:
                        msg = f"{shard_id}:{metadata['checksum']}:{metadata['size']}:{ts}:"
                    
                    # compute HMAC fallback
                    if shared:
                        h = make_hmac(shared, msg)
                        headers['X-P2P-HMAC'] = h
                        headers['X-P2P-TS'] = ts
                        
                    data.add_field('metadata', json.dumps(metadata), content_type='application/json')
                    data.add_field('file', file_bytes, filename=shard_id, content_type='application/octet-stream')

                    start = time.time()
                    async with session.post(url, data=data, headers=headers, timeout=30) as resp:
                        latency = time.time() - start
                        from .metrics import REPLICATION_PUSH_LATENCY_SECONDS
                        REPLICATION_PUSH_LATENCY_SECONDS.set(latency)
                        if resp.status == 200:
                            result = await resp.json()
                            if result.get('status') == 'ok' and result.get('checksum') == metadata['checksum']:
                                from .metrics import REPLICATION_PUSH_SUCCEEDED
                                REPLICATION_PUSH_SUCCEEDED.inc()
                                return True
                else:
                    # fallback: lightweight JSON notify
                    payload = {"shard_id": shard_id}
                    start = time.time()
                    async with session.post(url, json=payload, timeout=10) as resp:
                        latency = time.time() - start
                        from .metrics import REPLICATION_PUSH_LATENCY_SECONDS
                        REPLICATION_PUSH_LATENCY_SECONDS.set(latency)
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("status") == "ok":
                                from .metrics import REPLICATION_PUSH_SUCCEEDED
                                REPLICATION_PUSH_SUCCEEDED.inc()
                                return True
                            else:
                                from .metrics import REPLICATION_PUSH_FAILED
                                REPLICATION_PUSH_FAILED.inc()
                                return False
        except Exception as e:
            logger.debug("Push shard to %s failed: %s", addr, e)
            try:
                from .metrics import REPLICATION_PUSH_FAILED
                REPLICATION_PUSH_FAILED.inc()
            except Exception:
                pass
        return False

    async def ensure_replication(self, shard_id: str, data: bytes, peers: List[dict]):
        # Push data to peers until replication_factor achieved; require HTTP ack
        successes = 0
        for p in peers:
            for a in p.get("addrs", []):
                ok = await self._push_shard_to_addr(shard_id, a)
                if ok:
                    self.metadata.note_replica(shard_id, p.get("peer_id"))
                    successes += 1
                else:
                    self.metadata.remove_replica(shard_id, p.get("peer_id"))
                if successes >= self.replication_factor:
                    return successes
        return successes

