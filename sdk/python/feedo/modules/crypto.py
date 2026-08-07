import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from ecies import encrypt, decrypt
import binascii

class FeedoCrypto:
    @staticmethod
    def generate_symmetric_key() -> bytes:
        return os.urandom(32)

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
