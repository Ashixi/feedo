import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger("feedo_p2p_reputation")

class ReputationManager:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # Dictionary of pubkey_hex -> dict of balances
        # { "pubkey": { "tokens": 0, "provider_reputation": 0, "network_reputation": 0, "free_read_quota": 0 } }
        self._balances: Dict[str, Dict[str, int]] = {}
        self._load()

    def _ensure_schema(self, pubkey_hex: str):
        if pubkey_hex not in self._balances:
            self._balances[pubkey_hex] = {
                "tokens": 0,
                "provider_reputation": 0,
                "network_reputation": 0,
                "free_read_quota": 0
            }
        else:
            # Migration from old schema if needed (old schema was just int credits)
            if isinstance(self._balances[pubkey_hex], int):
                old_balance = self._balances[pubkey_hex]
                self._balances[pubkey_hex] = {
                    "tokens": old_balance,
                    "provider_reputation": 0,
                    "network_reputation": 0,
                    "free_read_quota": 0
                }

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as f:
                    self._balances = json.load(f)
                    
                    # Ensure schema for all loaded keys
                    for k in list(self._balances.keys()):
                        self._ensure_schema(k)
        except Exception as e:
            logger.warning(f"Failed to load reputation from {self.path}: {e}")
            self._balances = {}

    def _save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self._balances, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save reputation to {self.path}: {e}")

    def pay_for_query(self, pubkey_hex: str, cost: int = 1, allow_free_quota: bool = True) -> bool:
        if not pubkey_hex:
            # Allow anonymous for now with dry run logging
            logger.warning("[DRY-RUN] Anonymous query. Allowing anyway.")
            return True

        self._ensure_schema(pubkey_hex)
        
        # Try free quota first
        if allow_free_quota and self._balances[pubkey_hex].get("free_read_quota", 0) >= cost:
            self._balances[pubkey_hex]["free_read_quota"] -= cost
            logger.debug(f"Peer {pubkey_hex} paid {cost} from free_read_quota.")
            self._save()
            return True
            
        # Try tokens
        if self._balances[pubkey_hex].get("tokens", 0) >= cost:
            self._balances[pubkey_hex]["tokens"] -= cost
            logger.debug(f"Peer {pubkey_hex} paid {cost} from tokens.")
            self._save()
            return True
            
        logger.warning(f"[DRY-RUN] Peer {pubkey_hex} has insufficient funds for query cost {cost}. Allowing anyway for now.")
        return True # For dry-run, we return True, later we will return False

    def reward_query_hit(self, author_pubkey: str, compute_node_pubkey: str, fee_amount: int = 1):
        """Splits the query fee: 5% treasury, 15% author (tokens), 80% compute node (tokens)."""
        treasury_pubkey = os.getenv("TREASURY_PUBKEY", "treasury_default")
        
        if not author_pubkey:
            return
            
        self._ensure_schema(author_pubkey)
        self._ensure_schema(treasury_pubkey)
        
        if compute_node_pubkey:
            self._ensure_schema(compute_node_pubkey)
            
        treasury_share = int(fee_amount * 0.05)
        author_share = int(fee_amount * 0.15)
        compute_share = fee_amount - treasury_share - author_share
        
        self._balances[treasury_pubkey]["tokens"] += treasury_share
        self._balances[author_pubkey]["tokens"] += author_share
        self._balances[author_pubkey]["provider_reputation"] += 1
        
        if compute_node_pubkey:
            self._balances[compute_node_pubkey]["tokens"] += compute_share
            
        logger.debug(f"Query Hit: Treasury {treasury_share}, Author {author_share}, Compute {compute_share}")
        self._save()

    def reward_download_hit(self, author_pubkey: str, routing_node_pubkey: str, storage_nodes: list[str], fee_amount: int = 1):
        """Splits the download fee: 5% treasury, 10% author, 10% routing, 75% storage."""
        if not storage_nodes:
            return
            
        treasury_pubkey = os.getenv("TREASURY_PUBKEY", "treasury_default")
        self._ensure_schema(treasury_pubkey)
        
        treasury_share = int(fee_amount * 0.05)
        author_share = int(fee_amount * 0.10)
        routing_share = int(fee_amount * 0.10)
        storage_pool = fee_amount - treasury_share - author_share - routing_share
        
        storage_share_per_node = storage_pool // len(storage_nodes)
        
        self._balances[treasury_pubkey]["tokens"] += treasury_share
        
        if author_pubkey:
            self._ensure_schema(author_pubkey)
            self._balances[author_pubkey]["tokens"] += author_share
            
        if routing_node_pubkey:
            self._ensure_schema(routing_node_pubkey)
            self._balances[routing_node_pubkey]["tokens"] += routing_share
            
        for node in storage_nodes:
            if node:
                self._ensure_schema(node)
                self._balances[node]["tokens"] += storage_share_per_node
                
        logger.debug(f"Download Hit: Distributed {fee_amount} among Treasury, Author, Routing, and {len(storage_nodes)} Storage nodes.")
        self._save()

    def reward_unique_content(self, author_pubkey: str, reputation_amount: int = 10):
        if not author_pubkey:
            return
        self._ensure_schema(author_pubkey)
        self._balances[author_pubkey]["network_reputation"] += reputation_amount
        logger.debug(f"Peer {author_pubkey} earned {reputation_amount} network_reputation for unique content.")
        self._save()

    def refresh_daily_quotas(self):
        """Recalculate free read quota based on network reputation."""
        self.apply_reputation_decay(0.05) 
        for pubkey in self._balances:
            self._ensure_schema(pubkey)
            new_quota = self._balances[pubkey]["network_reputation"] * 5
            self._balances[pubkey]["free_read_quota"] = new_quota
        self._save()
        logger.info("Daily free read quotas refreshed.")

    def apply_reputation_decay(self, decay_rate: float = 0.05):
        """Reduces network reputation by decay_rate."""
        for pubkey in self._balances:
            self._ensure_schema(pubkey)
            current_rep = self._balances[pubkey]["network_reputation"]
            decay_amount = int(current_rep * decay_rate)
            self._balances[pubkey]["network_reputation"] = max(0, current_rep - decay_amount)
            
    def claim_tokens(self, pubkey_hex: str, amount: int, min_threshold: int = 5000) -> bool:
        """Attempt to claim tokens off-chain to move to on-chain."""
        if not pubkey_hex:
            return False
            
        self._ensure_schema(pubkey_hex)
        current = self._balances[pubkey_hex]["tokens"]
        
        if current < min_threshold or amount > current:
            return False
            
        self._balances[pubkey_hex]["tokens"] -= amount
        self._save()
        logger.info(f"Peer {pubkey_hex} claimed {amount} tokens (remaining: {self._balances[pubkey_hex]['tokens']})")
        return True

    def slash_storage_node(self, pubkey_hex: str, penalty_amount: int = 50):
        """Slash a node for failing to deliver data."""
        if not pubkey_hex:
            return
        self._ensure_schema(pubkey_hex)
        self._balances[pubkey_hex]["tokens"] -= penalty_amount
        logger.warning(f"Slashed peer {pubkey_hex} for {penalty_amount} tokens. New balance: {self._balances[pubkey_hex]['tokens']}")
        self._save()

    def reward_peer(self, pubkey_hex: str, amount: int = 1):
        if not pubkey_hex: return
        self._ensure_schema(pubkey_hex)
        self._balances[pubkey_hex]["tokens"] += amount
        self._save()

    def charge_peer(self, pubkey_hex: str, amount: int = 1):
        self.pay_for_query(pubkey_hex, amount, allow_free_quota=False)

    def can_afford(self, pubkey_hex: str, amount: int = 1) -> bool:
        if not pubkey_hex: return True
        self._ensure_schema(pubkey_hex)
        return self._balances[pubkey_hex]["tokens"] >= amount or self._balances[pubkey_hex]["free_read_quota"] >= amount
    
    def get_balances(self, pubkey_hex: str) -> Dict[str, int]:
        if not pubkey_hex:
            return {}
        self._ensure_schema(pubkey_hex)
        return self._balances[pubkey_hex]
