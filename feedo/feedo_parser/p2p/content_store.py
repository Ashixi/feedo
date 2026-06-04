import json
import os
import time
from typing import Dict, Optional, List


class ContentStore:
    """Persistent lightweight content index with tombstones and metadata.

    Stores entries as JSON: {hash: {data: {...}, last_modified: ts, tombstone: bool, origin: peer_id}}
    """

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._data: Dict[str, dict] = {}
        self._load()
        # directory to store shard binaries
        self.shard_dir = os.getenv('FEEDO_SHARD_STORAGE_DIR', os.path.join(os.path.dirname(path) or '.', 'shards'))
        os.makedirs(self.shard_dir, exist_ok=True)

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

    def add_item(self, hash_id: str, item: dict, origin: Optional[str] = None, last_modified: Optional[float] = None):
        now = last_modified or time.time()
        existing = self._data.get(hash_id)
        if existing:
            # conflict resolution: prefer newer last_modified; if equal, prefer higher origin id
            if existing.get("last_modified", 0) > now:
                return
            if existing.get("last_modified", 0) == now:
                if existing.get("origin", "") >= (origin or ""):
                    return

        self._data[hash_id] = {
            "data": item,
            "last_modified": now,
            "tombstone": False,
            "origin": origin or "",
            "file_path": self._data.get(hash_id, {}).get("file_path")
        }
        self._save()

    def save_binary_atomic(self, hash_id: str, data_bytes: bytes) -> str:
        """Save shard bytes atomically and return stored path."""
        tmp_path = os.path.join(self.shard_dir, f"{hash_id}.tmp")
        final_path = os.path.join(self.shard_dir, f"{hash_id}")
        try:
            with open(tmp_path, 'wb') as f:
                f.write(data_bytes)
            os.replace(tmp_path, final_path)
            # record path
            e = self._data.setdefault(hash_id, {})
            e['file_path'] = final_path
            e['last_modified'] = time.time()
            self._save()
            return final_path
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def has_file(self, hash_id: str) -> bool:
        e = self._data.get(hash_id)
        if not e:
            return False
        p = e.get('file_path')
        return bool(p and os.path.exists(p))

    def get_file_path(self, hash_id: str) -> Optional[str]:
        return self._data.get(hash_id, {}).get('file_path')

    def mark_tombstone(self, hash_id: str, origin: Optional[str] = None, ts: Optional[float] = None):
        now = ts or time.time()
        e = self._data.get(hash_id)
        if not e:
            self._data[hash_id] = {"data": None, "last_modified": now, "tombstone": True, "origin": origin or ""}
        else:
            # only update if newer
            if e.get("last_modified", 0) <= now:
                e["tombstone"] = True
                e["last_modified"] = now
                e["origin"] = origin or e.get("origin", "")
        self._save()

    def has(self, hash_id: str) -> bool:
        e = self._data.get(hash_id)
        return bool(e and not e.get("tombstone", False))

    def is_tombstoned(self, hash_id: str) -> bool:
        e = self._data.get(hash_id)
        return bool(e and e.get("tombstone", False))

    def get_item(self, hash_id: str) -> Optional[dict]:
        e = self._data.get(hash_id)
        if not e:
            return None
        return e.get("data")

    def summary(self, limit: int = 200) -> List[dict]:
        # return list of {hash, last_modified, tombstone}
        items = []
        for h, v in self._data.items():
            items.append({"hash": h, "last_modified": v.get("last_modified", 0), "tombstone": bool(v.get("tombstone", False))})
        items.sort(key=lambda x: x["last_modified"], reverse=True)
        return items[:limit]

    def missing_hashes_against(self, remote_summary: List[dict], limit: int = 100) -> List[str]:
        # remote_summary: list of {hash, last_modified}
        remote_map = {r["hash"]: r.get("last_modified", 0) for r in remote_summary}
        missing = []
        for h, v in self._data.items():
            local_ts = v.get("last_modified", 0)
            remote_ts = remote_map.get(h, 0)
            if local_ts > remote_ts:
                # remote is outdated or missing
                missing.append(h)
                if len(missing) >= limit:
                    break
        return missing
