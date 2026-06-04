import hmac
import hashlib
from typing import Optional

try:
    from nacl.signing import VerifyKey, SigningKey
    from nacl.exceptions import BadSignatureError
    _NACL_AVAILABLE = True
except Exception:
    _NACL_AVAILABLE = False


def make_hmac(secret: str, msg: str) -> str:
    return hmac.new(secret.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest()


def verify_hmac(secret: str, msg: str, signature: str) -> bool:
    try:
        expected = make_hmac(secret, msg)
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


def verify_ed25519(pubkey_hex: str, msg: bytes, signature_hex: str) -> bool:
    """Verify Ed25519 signature if libsodium (PyNaCl) available."""
    if not _NACL_AVAILABLE:
        return False
    try:
        vk = VerifyKey(bytes.fromhex(pubkey_hex))
        sig = bytes.fromhex(signature_hex)
        vk.verify(msg, sig)
        return True
    except BadSignatureError:
        return False
    except Exception:
        return False


def sign_ed25519(privkey_hex: str, msg: bytes) -> Optional[str]:
    """Sign a message using Ed25519 if libsodium (PyNaCl) available."""
    if not _NACL_AVAILABLE:
        return None
    try:
        sk = SigningKey(bytes.fromhex(privkey_hex))
        signed = sk.sign(msg)
        return signed.signature.hex()
    except Exception:
        return None
