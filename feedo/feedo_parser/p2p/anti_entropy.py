import asyncio
import logging
import json
import time
from typing import List

logger = logging.getLogger("feedo_p2p_anti_entropy")


class AntiEntropyManager:
    def __init__(self, store, gossip, cache, interval: int = 60):
        self.store = store
        self.gossip = gossip
        self.cache = cache
        self.interval = interval
        self._task = None
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass

    async def _loop(self):
        while self._running:
            try:
                await self._publish_summary()
            except Exception as e:
                logger.exception("anti-entropy publish failed: %s", e)
            await asyncio.sleep(self.interval)

    async def _publish_summary(self):
        summary = self.store.summary(limit=200)
        payload = {"summary": summary}
        try:
            await self.gossip.publish("anti_entropy_summary", payload)
        except Exception as e:
            logger.debug("Failed to send summary: %s", e)

    def handle_message(self, msg: dict):
        # handle incoming anti-entropy messages
        topic = msg.get("topic")
        pid = msg.get("peer_id")
        payload = msg.get("payload") or {}
        if not pid:
            return

        if topic == "anti_entropy_summary":
            remote_summary = payload.get("summary", [])
            missing = self.store.missing_hashes_against(remote_summary, limit=50)
            if missing:
                # request the missing hashes (we publish a fetch_request asking peers to respond)
                req = {"want": missing}
                try:
                    asyncio.create_task(self.gossip.publish("fetch_request", {"want": missing}))
                except Exception:
                    pass

        elif topic == "fetch_request":
            want = payload.get("want", [])
            to_send = []
            for h in want:
                item = self.store.get_item(h)
                tomb = self.store.is_tombstoned(h)
                if item is not None or tomb:
                    to_send.append({"hash": h, "data": item, "tombstone": tomb, "last_modified": self.store._data.get(h, {}).get("last_modified", 0)})
            if to_send:
                try:
                    asyncio.create_task(self.gossip.publish("fetch_response", {"items": to_send}))
                except Exception:
                    pass

        elif topic == "fetch_response":
            items = payload.get("items", [])
            for it in items:
                h = it.get("hash")
                if it.get("tombstone"):
                    self.store.mark_tombstone(h, origin=pid, ts=it.get("last_modified"))
                else:
                    data = it.get("data")
                    self.store.add_item(h, data, origin=pid, last_modified=it.get("last_modified"))
