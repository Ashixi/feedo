import json
import os
import time
from typing import Dict


class ReplayCache:
    def __init__(self, path: str, window: int = 300):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.window = window
        self._data: Dict[str, Dict[str, float]] = {}
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

    def seen(self, peer_id: str, nonce: str, ts: float) -> bool:
        now = time.time()
        if abs(now - ts) > self.window:
            return True  # too old
        peer_map = self._data.setdefault(peer_id, {})
        # cleanup
        for n, t in list(peer_map.items()):
            if now - t > self.window:
                peer_map.pop(n, None)
        if nonce in peer_map:
            return True
        peer_map[nonce] = ts
        self._save()
        return False
