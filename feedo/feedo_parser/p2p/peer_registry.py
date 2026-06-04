import json
import os
import time
from typing import Optional


class PeerRegistry:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._data = {}
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

    @property
    def peers(self):
        result = {}
        for pid, val in self._data.items():
            if isinstance(val, dict):
                result[pid] = val
            else:
                result[pid] = {"pubkey": val, "is_supernode": False, "last_seen": time.time()}
        return result

    def register(self, peer_id: str, pubkey_hex: str, is_supernode: bool = False):
        self._data[peer_id] = {
            "pubkey": pubkey_hex,
            "is_supernode": is_supernode,
            "last_seen": time.time()
        }
        self._save()

    def get_pubkey(self, peer_id: str) -> Optional[str]:
        val = self._data.get(peer_id)
        if isinstance(val, dict):
            return val.get("pubkey")
        return val
