import json
import os
import logging
from typing import Dict

logger = logging.getLogger("feedo_p2p_reputation")

class ReputationManager:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # Dictionary of pubkey_hex -> credits (int)
        self._balances: Dict[str, int] = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as f:
                    self._balances = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load reputation from {self.path}: {e}")
            self._balances = {}

    def _save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self._balances, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save reputation to {self.path}: {e}")

    def reward_peer(self, pubkey_hex: str, amount: int = 1):
        if not pubkey_hex:
            return
        current = self._balances.get(pubkey_hex, 0)
        self._balances[pubkey_hex] = current + amount
        logger.debug(f"Rewarded peer {pubkey_hex} with {amount} credits. New balance: {self._balances[pubkey_hex]}")
        self._save()

    def charge_peer(self, pubkey_hex: str, amount: int = 1):
        if not pubkey_hex:
            return
        current = self._balances.get(pubkey_hex, 0)
        self._balances[pubkey_hex] = current - amount
        logger.debug(f"Charged peer {pubkey_hex} with {amount} credits. New balance: {self._balances[pubkey_hex]}")
        self._save()

    def can_afford(self, pubkey_hex: str, amount: int = 1) -> bool:
        if not pubkey_hex:
            return True # Allow anonymous reads during dry-run phase
        
        current = self._balances.get(pubkey_hex, 0)
        if current < amount:
            # DRY-RUN MODE: We log a warning but still return True.
            # In the future, this should return False to block the request.
            logger.warning(f"[DRY-RUN] Peer {pubkey_hex} has insufficient karma (balance: {current}, required: {amount}). Allowing anyway.")
            return True
        return True
