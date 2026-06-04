"""Feedo protocol utilities package.
Exports core protocol components used by nodes and the app.
"""
from .vector_brain import VectorBrain
from .crypto_utils import generate_content_hash, generate_hash_id, sign_hash, verify_signature

__all__ = [
    "VectorBrain",
    "generate_content_hash",
    "generate_hash_id",
    "sign_hash",
    "verify_signature",
]
