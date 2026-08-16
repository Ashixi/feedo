"""
Synchronous memory store backed by the Feedo decentralized search network.

``FeedoMemory`` is a lightweight, framework-agnostic memory abstraction used to
integrate Feedo as a memory backend for AI agent frameworks (PraisonAI, etc.).

It provides synchronous methods (the agent frameworks call memory synchronously)
while the Feedo SDK itself is async. The class wraps the async calls internally.

Isolation
---------
Each user/tenant is isolated via a ``namespace`` on the shared Feedo network:

    feedo-memory:{user_id or DID}:{short|long}

Privacy
-------
- ``private=True`` (default): memories are indexed as owner-only ``private_post``
  items (the search node stores the vector, not the plaintext).
- ``private=False``: memories are indexed as public documents.

Auth
----
Delegated mode is supported: pass only ``usage_key`` and the owner DID is
auto-resolved from the delegation stored on the consensus network.
"""

import asyncio
import concurrent.futures
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx

from .client import FeedoClient
from .router import DEFAULT_SEEDS


def _run(coro):
    """Run an async coroutine synchronously, handling running event loops."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return asyncio.run(coro)
    if loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return loop.run_until_complete(coro)


def _resolve_did(usage_key: str, consensus_seeds: List[str]) -> Optional[str]:
    """Resolve the owner DID (0xW) for a delegated usage key (0xD).

    Queries ``GET /did/{usage_address}/delegation`` against the consensus seeds.
    Returns the owner DID string (``did:feedo:0x...``) or ``None``.
    """
    try:
        from eth_account import Account

        usage_addr = Account.from_key(usage_key).address
    except Exception:
        return None

    for seed in consensus_seeds:
        try:
            resp = httpx.get(f"{seed}/did/{usage_addr}/delegation", timeout=5.0)
            if resp.status_code == 200:
                owner = (resp.json() or {}).get("owner")
                if owner:
                    return owner
        except Exception:
            continue
    return None


class FeedoMemory:
    """Synchronous memory store backed by the Feedo decentralized network.

    Example:
        memory = FeedoMemory(usage_key="0x...")                  # private (default)
        memory = FeedoMemory(usage_key="0x...", private=False)   # public
        memory.add_long("User prefers dark mode", {"topic": "ui"})
        results = memory.search_long("dark mode")
    """

    def __init__(
        self,
        *,
        usage_key: Optional[str] = None,
        private_key: Optional[str] = None,
        did: Optional[str] = None,
        user_id: Optional[str] = None,
        private: bool = True,
        client: Optional[FeedoClient] = None,
        search_seeds: Optional[List[str]] = None,
        consensus_seeds: Optional[List[str]] = None,
        storage_seeds: Optional[List[str]] = None,
    ):
        if client is None and not usage_key and not private_key:
            raise ValueError(
                "FeedoMemory requires either `usage_key`, `private_key`, or an existing `client`."
            )

        consensus_seeds = consensus_seeds or DEFAULT_SEEDS["consensus"]

        # Auto-resolve the owner DID from the usage key's delegation.
        if client is None and did is None and usage_key and not private_key:
            did = _resolve_did(usage_key, consensus_seeds)
            if not did:
                raise ValueError(
                    "Could not auto-resolve DID from usage_key. Make sure the usage "
                    "key is delegated, or pass `did` explicitly."
                )

        self.client = client or FeedoClient(
            usage_key=usage_key,
            private_key=private_key,
            did=did,
            search_seeds=search_seeds,
            consensus_seeds=consensus_seeds,
            storage_seeds=storage_seeds,
        )
        self.private = private
        self.user_id = user_id

        # Namespace isolation: one namespace per user, split by memory tier.
        base = user_id or (did.split("did:feedo:")[-1] if did else "default")
        self._base_ns = f"feedo-memory:{base}"
        self._short_ns = f"{self._base_ns}:short"
        self._long_ns = f"{self._base_ns}:long"

    def _ns(self, tier: str) -> str:
        return self._short_ns if tier == "short" else self._long_ns

    def _run(self, coro):
        return _run(coro)

    def _add(self, text: str, metadata: Optional[Dict], tier: str) -> str:
        meta = dict(metadata or {})
        meta.setdefault("memory_tier", tier)
        ns = self._ns(tier)
        hash_id = "mem_" + uuid4().hex[:16]

        if self.private:
            self._run(
                self.client.search.index_private_document(
                    hash_id, text, metadata=meta, namespace=ns
                )
            )
        else:
            self._run(
                self.client.search.index_document(
                    text, metadata=meta, namespace=ns, hash_id=hash_id
                )
            )
        return hash_id

    def _search(self, query: str, limit: int, tier: str) -> List[Dict[str, Any]]:
        ns = self._ns(tier)
        item_type = "private_post" if self.private else "all"
        resp = self._run(
            self.client.search.search(
                query, limit=limit, namespace=ns, item_type=item_type
            )
        )
        results = (resp or {}).get("results", [])
        return [
            {
                "id": r.get("hash_id", ""),
                "text": r.get("text", ""),
                "metadata": r.get("metadata", {}) or {},
                "score": r.get("score", 0),
            }
            for r in results
        ]

    # ------------------------------------------------------------------
    # Public API (matches PraisonAI's MemoryProtocol)
    # ------------------------------------------------------------------

    def add_short(self, text: str, metadata: Optional[Dict] = None, **kwargs) -> str:
        """Store content in short-term memory. Returns the memory id."""
        return self._add(text, metadata, "short")

    def add_long(self, text: str, metadata: Optional[Dict] = None, **kwargs) -> str:
        """Store content in long-term memory. Returns the memory id."""
        return self._add(text, metadata, "long")

    def search_short(self, query: str, limit: int = 5, **kwargs) -> List[Dict[str, Any]]:
        """Search short-term memory. Returns a list of matching entries."""
        return self._search(query, limit, "short")

    def search_long(self, query: str, limit: int = 5, **kwargs) -> List[Dict[str, Any]]:
        """Search long-term memory. Returns a list of matching entries."""
        return self._search(query, limit, "long")

    def get_all_memories(self, **kwargs) -> List[Dict[str, Any]]:
        """Return all stored memories (short + long) for this user."""
        out: List[Dict[str, Any]] = []
        for ns in (self._short_ns, self._long_ns):
            resp = self._run(
                self.client.search.get_documents(namespace=ns, limit=1000)
            )
            for r in (resp or {}).get("results", []):
                out.append(
                    {
                        "id": r.get("hash_id", ""),
                        "text": r.get("text", ""),
                        "metadata": r.get("metadata", {}) or {},
                    }
                )
        return out

    def clear_short(self) -> None:
        """Clear all short-term memories."""
        self._run(self.client.search.delete_by_namespace(self._short_ns))

    def clear_long(self) -> None:
        """Clear all long-term memories."""
        self._run(self.client.search.delete_by_namespace(self._long_ns))