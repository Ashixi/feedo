import json
import os
import time
from typing import Dict, List


class ReplicationMetadata:
    """Simple persistent mapping: shard_id -> {peers: {peer_id: last_seen_ts}, desired_replication}
    """

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._data: Dict[str, dict] = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
        except Exception:
            self._data = {}

    def _save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2)
        except Exception:
            pass

    def note_replica(self, shard_id: str, peer_id: str, ts: float = None):
        ts = ts or time.time()
        e = self._data.setdefault(shard_id, {"peers": {}, "desired": 3})
        e["peers"][peer_id] = ts
        self._save()

    def remove_replica(self, shard_id: str, peer_id: str):
        e = self._data.get(shard_id)
        if not e:
            return
        e["peers"].pop(peer_id, None)
        self._save()

    def replicas(self, shard_id: str) -> List[str]:
        e = self._data.get(shard_id)
        if not e:
            return []
        return list(e.get("peers", {}).keys())

    def replica_count(self, shard_id: str) -> int:
        return len(self.replicas(shard_id))

    def ensure_desired(self, shard_id: str, desired: int):
        e = self._data.setdefault(shard_id, {"peers": {}, "desired": desired})
        e["desired"] = desired
        self._save()
