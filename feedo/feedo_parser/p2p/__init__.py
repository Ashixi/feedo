"""Simple P2P helpers for Feedo (discovery, peer cache, replication scaffolding).

This package provides a lightweight, self-contained P2P subsystem used by the
Python API. It's not a full libp2p implementation but provides working
functionality for LAN discovery, gossipsub-style announce over UDP broadcast,
persistent peer cache, a stable peer id, periodic dialing, and scaffolding for
replication and anti-entropy.
"""

from .manager import P2PManager  # re-export
