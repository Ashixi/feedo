import json
import os
import uuid
import secrets
from typing import Dict

try:
    from nacl.signing import SigningKey
    _NACL_AVAILABLE = True
except Exception:
    _NACL_AVAILABLE = False


def load_or_create_peer_key(path: str) -> Dict[str, str]:
    """Load a stable peer id from `path` or create one if missing.

    The stored format is a small JSON with `peer_id`, `secret`, `pubkey_hex`, and `privkey_hex`.
    This keeps a stable identity across restarts.
    """
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "pubkey_hex" in data and "privkey_hex" in data:
                    return data
    except Exception:
        # fall through to recreate
        pass

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = {"peer_id": uuid.uuid4().hex, "secret": secrets.token_hex(32)}
    
    if _NACL_AVAILABLE:
        try:
            sk = SigningKey.generate()
            data["privkey_hex"] = sk.encode().hex()
            data["pubkey_hex"] = sk.verify_key.encode().hex()
        except Exception:
            pass

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data
