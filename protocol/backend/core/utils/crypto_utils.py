import hashlib
import nacl.signing
import nacl.exceptions
from datetime import datetime

def generate_keys_from_password(password: str) -> tuple[str, str]:
    """Використовується ТІЛЬКИ для системного акаунта (RSS-ноди)."""
    seed = hashlib.sha256(password.encode('utf-8')).digest()
    signing_key = nacl.signing.SigningKey(seed)
    verify_key = signing_key.verify_key
    # Returns 64-byte secret key and 32-byte public key as hex
    sk_hex = bytes(signing_key) + bytes(verify_key)
    return sk_hex.hex(), bytes(verify_key).hex()

def generate_hash_id(text_content: str, timestamp: datetime) -> str: 
    """Генерує унікальний хеш події/поста (залежить від часу)."""
    # For JS compatibility we used timestamp as unix seconds, but let's just make sure both match
    # Since this function is mostly for older code, we keep it as is. But for JS we use int timestamp.
    data = f"{text_content}_{timestamp.isoformat()}"
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

def generate_content_hash(text_content: str) -> str:
    """Генерує хеш тільки контенту (стабільний, ключ для DHT)."""
    return hashlib.sha256(text_content.encode('utf-8')).hexdigest()

def sign_hash(hash_id: str, private_key_hex: str) -> str:
    """Підписує хеш."""
    sk_bytes = bytes.fromhex(private_key_hex)
    if len(sk_bytes) == 64:
        sk_bytes = sk_bytes[:32] # PyNaCl uses 32-byte seed
    signing_key = nacl.signing.SigningKey(sk_bytes)
    digest = bytes.fromhex(hash_id)
    signed = signing_key.sign(digest)
    return signed.signature.hex()

def verify_signature(hash_id: str, signature_hex: str, wallet_address_hex: str) -> bool:
    """Універсальна перевірка підпису (Ed25519)."""
    try:
        vk_bytes = bytes.fromhex(wallet_address_hex.replace("0x", ""))
        verify_key = nacl.signing.VerifyKey(vk_bytes)
        signature_bytes = bytes.fromhex(signature_hex.replace("0x", ""))
        digest = bytes.fromhex(hash_id)

        verify_key.verify(digest, signature_bytes)
        return True
    except (nacl.exceptions.BadSignatureError, ValueError, Exception):
        return False

def verify_nostr_signature(pubkey_hex: str, message_or_hash: str, signature_hex: str, is_hash: bool = False) -> bool:
    try:
        import coincurve
        if is_hash:
            msg_hash = bytes.fromhex(message_or_hash)
        else:
            msg_hash = hashlib.sha256(message_or_hash.encode('utf-8')).digest()
        
        # Nostr pubkeys are 32-byte x-only. Try PublicKeyXOnly first (newer coincurve)
        if hasattr(coincurve, 'PublicKeyXOnly'):
            pk = coincurve.PublicKeyXOnly(bytes.fromhex(pubkey_hex))
            if hasattr(pk, 'verify'):
                return pk.verify(bytes.fromhex(signature_hex), msg_hash)
            elif hasattr(pk, 'schnorr_verify'):
                return pk.schnorr_verify(bytes.fromhex(signature_hex), msg_hash)
            return False
        else:
            # Fallback for older coincurve versions
            pk = coincurve.PublicKey(bytes.fromhex('02' + pubkey_hex))
            if hasattr(pk, 'schnorr_verify'):
                return pk.schnorr_verify(bytes.fromhex(signature_hex), msg_hash)
            return False
    except Exception as e:
        print(f"Signature verification error: {e}")
        return False
