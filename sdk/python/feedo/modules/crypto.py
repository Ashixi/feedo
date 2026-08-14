import os
import hmac
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from ecies import encrypt, decrypt
import binascii
from eth_account import Account

class FeedoCrypto:
    @staticmethod
    def generate_symmetric_key() -> bytes:
        return os.urandom(32)

    @staticmethod
    def derive_usage_key(wallet_private_key_hex: str) -> dict:
        """
        Deterministically derive the usage key (0xD) from the wallet key (0xW).

        usage_sk = HMAC-SHA256(key=wallet_sk, msg="feedo/usage-key/v1") mod n

        Returns {"private_key": "0x...", "address": "0x..."}.
        The derived key can sign requests but cannot move funds (USDT stay on 0xW).
        """
        sk_bytes = bytes.fromhex(wallet_private_key_hex.replace("0x", ""))
        digest = hmac.new(sk_bytes, b"feedo/usage-key/v1", hashlib.sha256).digest()
        usage_int = int.from_bytes(digest, "big")
        # secp256k1 group order n (reduction is negligible in practice, keeps the key valid)
        n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        usage_int = usage_int % n
        if usage_int == 0:
            usage_int = 1
        usage_hex = format(usage_int, "064x")
        account = Account.from_key(usage_hex)
        return {"private_key": "0x" + usage_hex, "address": account.address}

    @staticmethod
    def encrypt_data(key: bytes, data: bytes) -> bytes:
        nonce = os.urandom(12)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(data) + encryptor.finalize()
        return nonce + ciphertext + encryptor.tag

    @staticmethod
    def decrypt_data(key: bytes, encrypted_data: bytes) -> bytes:
        if len(encrypted_data) < 28:
            raise ValueError("Data is too short to be AES-GCM encrypted")
        nonce = encrypted_data[:12]
        tag = encrypted_data[-16:]
        ciphertext = encrypted_data[12:-16]
        
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
        decryptor = cipher.decryptor()
        return decryptor.update(ciphertext) + decryptor.finalize()

    @staticmethod
    def encrypt_symmetric_key_ecies(public_key_hex: str, key: bytes) -> str:
        """
        public_key_hex: hex string of secp256k1 public key
        returns: hex string of the ECIES encrypted symmetric key
        """
        # Ensure it's uncompressed format if needed, eciespy accepts standard formats
        pub_bytes = binascii.unhexlify(public_key_hex.replace("0x", ""))
        encrypted = encrypt(public_key_hex, key)
        return binascii.hexlify(encrypted).decode('utf-8')

    @staticmethod
    def decrypt_symmetric_key_ecies(private_key_hex: str, encrypted_key_hex: str) -> bytes:
        """
        private_key_hex: hex string of secp256k1 private key
        encrypted_key_hex: hex string of the ECIES encrypted symmetric key
        returns: decrypted symmetric key bytes
        """
        enc_bytes = binascii.unhexlify(encrypted_key_hex.replace("0x", ""))
        return decrypt(private_key_hex, enc_bytes)
