from typing import List, Optional
from .router import NodeRouter
from .modules.search import SearchModule
from .modules.consensus import ConsensusModule
from .modules.storage import StorageModule
from .modules.crypto import FeedoCrypto
from eth_account import Account
from eth_account.messages import encode_defunct

class FeedoClient:
    def __init__(
        self,
        search_seeds: Optional[List[str]] = None,
        consensus_seeds: Optional[List[str]] = None,
        storage_seeds: Optional[List[str]] = None,
        private_key: Optional[str] = None
    ):
        self.router = NodeRouter(search_seeds, consensus_seeds, storage_seeds)
        self.private_key = private_key
        
        self.search = SearchModule(self.router, self.private_key)
        self.consensus = ConsensusModule(self.router, self.private_key)
        self.storage = StorageModule(self.router, self.private_key)

    async def upload_private_file(
        self,
        file_data: bytes,
        grantee_public_key_hex: Optional[str] = None,
        index_for_search: bool = True,
        metadata: dict = None
    ) -> str:
        """
        Encrypt and upload a file. Optionally grant access to another DID and index for search.
        
        Args:
            file_data: Raw bytes of the file to upload.
            grantee_public_key_hex: Public key of the grantee. If None, grants access to self.
            index_for_search: If True and file is text, index it in the Search Node.
            metadata: Optional metadata dict (e.g. {"app_id": "com.myapp", "type": "post"}).
        
        Returns:
            The hash ID of the uploaded encrypted file.
        """
        if not self.private_key:
            raise ValueError("Private key required to upload private files")
            
        my_account = Account.from_key(self.private_key)
        my_did = f"did:feedo:{my_account.address}"
        my_public_key = my_account._key_obj.public_key.to_hex()
        
        # If no grantee specified, encrypt for self
        target_pub_key = grantee_public_key_hex or my_public_key
        target_did = "unknown" if grantee_public_key_hex else my_did
        
        sym_key = FeedoCrypto.generate_symmetric_key()
        encrypted_data = FeedoCrypto.encrypt_data(sym_key, file_data)
        
        # Upload encrypted bytes directly
        hash_id = await self.storage.upload_bytes(encrypted_data, "encrypted_file.bin")
        
        # Encrypt symmetric key for the grantee
        enc_sym_key = FeedoCrypto.encrypt_symmetric_key_ecies(target_pub_key, sym_key)
        
        # Sign the grant payload
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
        
        # Optionally index plaintext in search node for private semantic search
        if index_for_search and target_did == my_did:
            try:
                text_content = file_data.decode('utf-8')
                await self.search.index_private_document(hash_id, text_content, metadata)
            except UnicodeDecodeError:
                pass  # Not text, skip indexing
        
        return hash_id

    async def download_private_file(self, hash_id: str) -> bytes:
        """
        Download and decrypt a private file.
        
        Args:
            hash_id: The hash ID of the encrypted file.
        
        Returns:
            Decrypted file bytes.
        """
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
        private_key_hex = my_account._key_obj.private_key.to_hex()
        sym_key = FeedoCrypto.decrypt_symmetric_key_ecies(private_key_hex, enc_sym_key)
        
        # 3. Download encrypted file from storage node
        encrypted_data = await self.storage.download_file(hash_id)
        
        # 4. Decrypt file data
        return FeedoCrypto.decrypt_data(sym_key, encrypted_data)
