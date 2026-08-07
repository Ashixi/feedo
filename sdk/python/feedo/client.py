from typing import List, Optional
from .router import NodeRouter
from .modules.search import SearchModule
from .modules.consensus import ConsensusModule
from .modules.storage import StorageModule
from .modules.crypto import FeedoCrypto
from eth_account import Account
from eth_account.messages import encode_defunct
import tempfile
import os

class FeedoClient:
    def __init__(self, search_seeds: Optional[List[str]] = None, consensus_seeds: Optional[List[str]] = None, storage_seeds: Optional[List[str]] = None, private_key: Optional[str] = None):
        self.router = NodeRouter(search_seeds, consensus_seeds, storage_seeds)
        self.private_key = private_key
        
        self.search = SearchModule(self.router, self.private_key)
        self.consensus = ConsensusModule(self.router, self.private_key)
        self.storage = StorageModule(self.router, self.private_key)

    async def upload_private_file(self, file_path: str, grantee_public_key_hex: Optional[str] = None, index_for_search: bool = True, metadata: dict = None) -> str:
        if not self.private_key:
            raise ValueError("Private key required to upload private files")
            
        my_account = Account.from_key(self.private_key)
        my_did = f"did:feedo:{my_account.address}"
        my_public_key = my_account._key_obj.public_key.to_hex()
        
        # If no grantee specified, encrypt for oneself
        target_pub_key = grantee_public_key_hex or my_public_key
        target_did = my_did if not grantee_public_key_hex else "unknown" # Actually we'd need DID for grantee, but for self it's my_did
        
        with open(file_path, "rb") as f:
            data = f.read()
            
        sym_key = FeedoCrypto.generate_symmetric_key()
        encrypted_data = FeedoCrypto.encrypt_data(sym_key, data)
        
        # Temporary file to upload
        fd, temp_path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(encrypted_data)
            
            # Upload encrypted data
            hash_id = await self.storage.upload_file(temp_path)
            
            # Encrypt symmetric key for the grantee
            enc_sym_key = FeedoCrypto.encrypt_symmetric_key_ecies(target_pub_key, sym_key)
            
            # Sign the grant
            payload_bytes = f"{hash_id}{target_did}{enc_sym_key}".encode('utf-8')
            message = encode_defunct(text=payload_bytes.decode('utf-8'))
            signed = Account.sign_message(message, private_key=self.private_key)
            
            # Grant access on consensus node
            await self.consensus.grant_file_access(
                file_hash=hash_id,
                grantee_did=target_did,
                encrypted_symmetric_key=enc_sym_key,
                public_key=my_public_key,
                signature_hex=signed.signature.hex()
            )
            
            # Optionally index on search node for private semantic search
            if index_for_search and target_did == my_did:
                try:
                    text_content = data.decode('utf-8')
                    await self.search.index_private_document(hash_id, text_content, metadata)
                except UnicodeDecodeError:
                    pass # Not text, cannot index for search
            
            return hash_id
        finally:
            os.remove(temp_path)

    async def download_private_file(self, hash_id: str) -> bytes:
        if not self.private_key:
            raise ValueError("Private key required to download private files")
            
        my_account = Account.from_key(self.private_key)
        my_did = f"did:feedo:{my_account.address}"
        
        # 1. Get encrypted symmetric key from consensus node
        res = await self.consensus.get_file_access(hash_id, my_did)
        enc_sym_key = res.get("encrypted_symmetric_key")
        if not enc_sym_key:
            raise PermissionError(f"No access granted for {my_did} to file {hash_id}")
            
        # 2. Decrypt symmetric key
        private_key_hex = hex(my_account._key_obj.private_key.int_value)
        sym_key = FeedoCrypto.decrypt_symmetric_key_ecies(private_key_hex, enc_sym_key)
        
        # 3. Download encrypted file from storage node
        encrypted_data = await self.storage.download_file(hash_id)
        
        # 4. Decrypt file data
        data = FeedoCrypto.decrypt_data(sym_key, encrypted_data)
        return data
