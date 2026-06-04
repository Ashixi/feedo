import json
import os
import time
from typing import Dict, List, Optional


class PeerCache:
    def __init__(self, path: str):
        self.path = path
        self._data: Dict[str, dict] = {}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        except Exception:
            self._data = {}

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception:
            pass

    def add_or_update(self, peer_id: str, addrs: List[str], score: float = 0.0):
        now = int(time.time())
        entry = self._data.get(peer_id, {})
        entry["peer_id"] = peer_id
        entry.setdefault("addrs", [])
        for a in addrs:
            if a not in entry["addrs"]:
                entry["addrs"].append(a)
        entry["score"] = max(entry.get("score", 0.0), score)
        entry["last_seen"] = now
        entry.setdefault("ttl", 3600)
        entry.setdefault("blacklist_until", 0)
        entry.setdefault("retries", 0)
        self._data[peer_id] = entry
        self._save()

    def mark_failure(self, peer_id: str):
        e = self._data.get(peer_id)
        if not e:
            return
        e["retries"] = e.get("retries", 0) + 1
        # degrade score
        e["score"] = max(0.0, e.get("score", 0.0) - 1.0)
        if e["retries"] > 5:
            e["blacklist_until"] = int(time.time()) + 300
        self._save()

    def mark_success(self, peer_id: str):
        e = self._data.get(peer_id)
        if not e:
            return
        e["retries"] = 0
        e["score"] = e.get("score", 0.0) + 1.0
        e["blacklist_until"] = 0
        self._save()

    def get_best_peers(self, limit: int = 10):
        now = int(time.time())
        items = []
        for pid, e in self._data.items():
            if e.get("blacklist_until", 0) > now:
                continue
            ttl = e.get("ttl", 3600)
            if now - int(e.get("last_seen", 0)) > ttl:
                continue
            items.append((e.get("score", 0.0), pid, e))
        items.sort(reverse=True, key=lambda x: x[0])
        return [e for _, _, e in items[:limit]]

    def peers(self):
        return list(self._data.values())
