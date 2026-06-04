import hashlib
import ecdsa
from datetime import datetime

def generate_keys_from_password(password: str) -> tuple[str, str]:
    """Використовується ТІЛЬКИ для системного акаунта (RSS-ноди)."""
    seed = hashlib.sha256(password.encode('utf-8')).digest()
    sk = ecdsa.SigningKey.from_string(seed, curve=ecdsa.SECP256k1)
    vk = sk.get_verifying_key()
    return sk.to_string().hex(), vk.to_string().hex()

def generate_hash_id(text_content: str, timestamp: datetime) -> str: 
    """Генерує унікальний хеш події/поста (залежить від часу)."""
    data = f"{text_content}_{timestamp.isoformat()}"
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

def generate_content_hash(text_content: str) -> str:
    """Генерує хеш тільки контенту (стабільний, ключ для DHT)."""
    return hashlib.sha256(text_content.encode('utf-8')).hexdigest()

def sign_hash(hash_id: str, private_key_hex: str) -> str:
    """Підписує хеш."""
    sk = ecdsa.SigningKey.from_string(bytes.fromhex(private_key_hex), curve=ecdsa.SECP256k1)
    return sk.sign_digest(bytes.fromhex(hash_id)).hex()

def verify_signature(hash_id: str, signature_hex: str, wallet_address_hex: str) -> bool:
    """Універсальна перевірка підпису."""
    try:
        vk = ecdsa.VerifyingKey.from_string(bytes.fromhex(wallet_address_hex.removeprefix("0x")), curve=ecdsa.SECP256k1)
        signature_bytes = bytes.fromhex(signature_hex.removeprefix("0x"))
        digest = bytes.fromhex(hash_id)

        if len(signature_bytes) == 64:
            return vk.verify_digest( 
                signature_bytes,
                digest,
                sigdecode=ecdsa.util.sigdecode_string,
            )

        try:
            return vk.verify_digest(signature_bytes, digest)
        except Exception:
            return vk.verify_digest(
                signature_bytes,
                digest,
                sigdecode=ecdsa.util.sigdecode_string,
            )
    except Exception:
        return False
