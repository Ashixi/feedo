# Feedo Protocol Python SDK

The official Developer SDK for interacting with the Feedo Protocol.

Feedo is a decentralized network consisting of Search, Consensus, and Storage nodes. This SDK provides a unified, asynchronous interface to interact with all layers of the Feedo Protocol.

## Features

- **Dynamic Node Routing:** The SDK automatically pings seed nodes and routes your requests to the fastest available node. If a node goes offline, the router instantly falls back to another healthy node.
- **Fully Asynchronous:** Built on top of `httpx` and `asyncio` for maximum performance in AI agents and backend applications.
- **End-to-End Encryption:** Built-in E2EE using AES-256-GCM and ECIES for private file storage.
- **DID Authentication:** Every request is signed with your Ethereum wallet key, verified by the Consensus and Storage nodes.

## Installation

```bash
pip install feedo-sdk
```

## Initialization

The SDK requires an event loop since it is entirely async. You do not need to specify URLs for the nodes; the SDK auto-discovers the fastest connection.

```python
import asyncio
from feedo import FeedoClient

async def main():
    client = FeedoClient()
    # Your code here

asyncio.run(main())
```

To perform authenticated operations (upload, index, search private files), provide your wallet's private key:

```python
from feedo import FeedoClient

client = FeedoClient(
    private_key="0x...",   # your wallet private key
    storage_seeds=["http://localhost:3001"],
    consensus_seeds=["http://localhost:3000"],
    search_seeds=["http://localhost:8000"],
)
```

*(Optional) Custom seed nodes for private clusters:*
```python
client = FeedoClient(
    search_seeds=["https://my-search.node"],
    consensus_seeds=["https://my-consensus.node"],
    storage_seeds=["https://my-storage.node"]
)
```

---

## ⚠️ Important: Registering Your DID

Before you can perform **any write operations** (uploading files, indexing documents, granting access), you **MUST** register your Decentralized Identifier (DID) on the Feedo Consensus network.

Registering your DID creates your identity on the blockchain and grants you the initial credits (500,000 credits) needed to pay for storage and compute. Without a registered DID, the storage nodes will reject your uploads due to "insufficient balance".

You only need to do this **once per wallet**.

```python
import asyncio
from eth_account import Account
from feedo import FeedoClient

async def main():
    account = Account.create()

    client = FeedoClient(private_key=account.key.hex())

    # 1. Register the DID on the network
    await client.consensus.register_did(account.key.hex())
    print("DID Registered successfully! You can now upload files.")

asyncio.run(main())
```

---

## Quick Start — Full E2EE Flow

```python
import asyncio
from eth_account import Account
from feedo import FeedoClient

async def main():
    account = Account.create()

    client = FeedoClient(
        private_key=account.key.hex(),
        storage_seeds=["http://localhost:3001"],
        consensus_seeds=["http://localhost:3000"],
        search_seeds=["http://localhost:8000"],
    )

    # 1. Register your DID on the network
    await client.consensus.register_did(account.key.hex())

    # 2. Upload an encrypted private file and index it for search
    content = b"My secret post content"
    hash_id = await client.upload_private_file(
        content,
        index_for_search=True,
        metadata={"app_id": "com.myapp", "type": "post"}
    )
    print("Hash:", hash_id)

    # 3. Search your private files
    results = await client.search.query("secret", limit=10, app_id="com.myapp")
    print(results)

asyncio.run(main())
```

---

## Search Module (`client.search`)

The Search module handles semantic queries and document vectorization.

### `query(query_text, limit=10, item_type="all", app_id=None)`
Perform a semantic search across the network.
```python
response = await client.search.query("DeFi protocols", limit=5, item_type="post", app_id="SocialApp1")
print(response.get("results", []))
```

### `get_documents(limit=50, offset=0, item_type="all", app_id=None)`
Fetch a feed of the latest indexed documents.
```python
feed = await client.search.get_documents(item_type="post", app_id="SocialApp1")
```

### `index_document(content, metadata=None)`
Index a public document into the vector database.
```python
await client.search.index_document("Bitcoin is decentralized.", {"type": "post"})
```

### `index_private_document(hash_id, plaintext, metadata=None)`
Index a **private** document (requires `private_key` to sign the request).
```python
await client.search.index_private_document(hash_id, "My private content", {"app_id": "com.myapp"})
```

### `get_stats()`
Retrieve network statistics.
```python
stats = await client.search.get_stats()
```

---

## Consensus Module (`client.consensus`)

The Consensus module manages identity (DIDs), naming (.feedo domains), and grants.

### `register_did(private_key_hex)`
Register a new Decentralized Identifier on the network.
```python
await client.consensus.register_did(account.key.hex())
```

### `resolve_name(name)`
Resolve a `.feedo` domain to its underlying CID.
```python
info = await client.consensus.resolve_name("my-app.feedo")
print(info['cid'])
```

### `get_did_balance(did)`
Check the credit balance of a specific DID.
```python
balance = await client.consensus.get_did_balance("did:feedo:0xabc...")
print(balance['balance_credits'])
```

### `register_name(name, did, cid, signature_hex)`
Register a new `.feedo` domain.
```python
await client.consensus.register_name("my-app", "did:feedo:...", "Qm...", "0x...")
```

### `grant_file_access(file_hash, grantee_did, encrypted_sym_key, public_key, signature)`
Grant another DID access to an encrypted file.
```python
await client.consensus.grant_file_access(hash_id, grantee_did, enc_key, pub_key, sig)
```

---

## Storage Module (`client.storage`)

The Storage module acts as a decentralized file system.

### `upload_file(file_data, filename="file")`
Upload raw bytes to the network. Returns the file hash ID.
```python
with open("./image.png", "rb") as f:
    hash_id = await client.storage.upload_file(f.read(), "image.png")
print("Hash:", hash_id)
```

### `download_file(hash_id) -> bytes`
Download a file from the network by its hash.
```python
raw_data = await client.storage.download_file("abc123...")
with open("downloaded.png", "wb") as f:
    f.write(raw_data)
```

### `get_recent_files()`
Get a list of recently uploaded files.
```python
recent = await client.storage.get_recent_files()
```

---

## E2EE Private Files (End-to-End Encryption)

The SDK provides built-in End-to-End Encryption using AES-256-GCM and ECIES. You need to provide a `private_key` in the client config.

### `upload_private_file(file_data, grantee_public_key_hex=None, index_for_search=True, metadata=None)`
Uploads a file securely. The file is AES-encrypted locally.
```python
content = b"My secret diary entry"
hash_id = await client.upload_private_file(
    content,
    index_for_search=True,
    metadata={"app_id": "com.myapp", "type": "note"}
)
print("Encrypted File Hash:", hash_id)
```

### `download_private_file(hash_id) -> bytes`
Downloads and automatically decrypts a private file (if your DID has access).
```python
decrypted = await client.download_private_file("abc123...")
print(decrypted.decode("utf-8"))
```

#### How it works under the hood:
1. **Client-Side Encryption:** Your file is encrypted locally using AES-256-GCM with a random symmetric key.
2. **Secure Storage:** The encrypted blob is uploaded to the **Storage Node** (which cannot read the content).
3. **Access Management:** The symmetric key is ECIES-encrypted for the grantee and stored on the **Consensus Node**.
4. **Private Vectorization:** If `index_for_search` is True, the plaintext is sent to the **Search Node** for vectorization. The plaintext is immediately discarded after embedding.

---

## DID Authentication

All write operations require signed `X-Feedo-*` headers. The SDK handles this automatically when you provide a `private_key`:

```
X-Feedo-DID:       did:feedo:0xYourAddress
X-Feedo-Timestamp: 1722345678901
X-Feedo-Signature: 0x<ECDSA signature of "FeedoAction:METHOD:PATH:TIMESTAMP">
```

---

## Error Handling

The SDK handles node failover automatically. Wrap network calls in `try/except`:

```python
try:
    results = await client.search.query("DeFi protocols")
except Exception as e:
    print(f"Feedo Protocol Error: {e}")
```

---

## Contributing

We welcome contributions to the Feedo Protocol SDK!  
GitHub Repository: [https://github.com/Ashixi/feedo](https://github.com/Ashixi/feedo)

1. Fork the repository.
2. Create your feature branch (`git checkout -b feature/amazing-feature`).
3. Commit your changes (`git commit -m 'Add some amazing feature'`).
4. Push to the branch (`git push origin feature/amazing-feature`).
5. Open a Pull Request.

## License

Apache License 2.0
