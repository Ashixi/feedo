import hashlib
import time
import requests
from ecdsa import SigningKey, SECP256k1

class FeedoClient:
    def __init__(self, private_key_hex: str, api_url: str = "http://127.0.0.1:8040"):
        self.api_url = api_url.rstrip("/")
        self.private_key_hex = private_key_hex.replace("0x", "")
        self.sk = SigningKey.from_string(bytes.fromhex(self.private_key_hex), curve=SECP256k1)
        # Compressed pubkey format 02/03 + 32 bytes
        vk_string = self.sk.verifying_key.to_string("compressed")
        self.public_key_hex = vk_string.hex()

    def _sha256(self, msg: str) -> str:
        return hashlib.sha256(msg.encode('utf-8')).hexdigest()

    def publish(self, content: str, title: str = None, source_type: str = "native"):
        hash_id = self._sha256(content + str(int(time.time())))
        content_blob_hash = self._sha256(content)
        
        # Sign the hash_id
        msg_hash_bytes = bytes.fromhex(hash_id)
        signature_bytes = self.sk.sign_digest_deterministic(msg_hash_bytes)
        signature = signature_bytes.hex()
        
        payload = {
            "author": self.public_key_hex,
            "hash_id": hash_id,
            "content_blob_hash": content_blob_hash,
            "signature": signature,
            "title": title,
            "text": content,
            "source_type": source_type,
            "sequence_number": 1
        }
        
        resp = requests.post(f"{self.api_url}/local/publish", json=payload)
        resp.raise_for_status()
        return resp.json()
        
    def query(self, text: str, federated: bool = False):
        params = {"text": text}
        if federated:
            params["federated"] = "true"
        resp = requests.get(f"{self.api_url}/query", params=params)
        resp.raise_for_status()
        return resp.json()
