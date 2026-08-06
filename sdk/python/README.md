# Feedo Protocol Python SDK

The official Developer SDK for interacting with the Feedo Protocol.

Feedo is a decentralized network consisting of Search, Consensus, and Storage nodes. This SDK provides a unified, asynchronous interface to interact with all layers of the Feedo Protocol.

## Features

- **Dynamic Node Routing:** The SDK automatically pings seed nodes and routes your requests to the fastest available node. If a node goes offline, the router instantly falls back to another healthy node.
- **Fully Asynchronous:** Built on top of `httpx` and `asyncio` for maximum performance in AI agents and backend applications.
- **Search Module:** Execute semantic vector queries, index new documents, and manage deployed websites.
- **Consensus Module:** Register Decentralized Identifiers (DIDs), resolve `.feedo` names, and manage network grants.
- **Storage Module:** Upload, download, and subscribe to data streams on the decentralized storage layer.

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

*(Optional) Custom seed nodes for private clusters:*
```python
client = FeedoClient(
    search_seeds=["https://my-search.node"],
    consensus_seeds=["https://my-consensus.node"],
    storage_seeds=["https://my-storage.node"]
)
```

---

## Search Module (`client.search`)

The Search module handles semantic queries and document vectorization.

### `query(query_text: str, limit: int = 10, item_type: str = "all")`
Perform a semantic search across the network, optionally filtering by item type.
```python
# Example: Search only within 'post' items
response = await client.search.query("DeFi protocols", limit=5, item_type="post")
print(response.get("results", []))
```

### `index_document(content: str, metadata: dict = None)`
Index a raw document into the vector database. The `metadata['type']` property automatically maps to the backend `item_type` for filtering.
```python
await client.search.index_document("Bitcoin is decentralized.", {"type": "post", "source": "wiki"})
```

### `deploy_proxy(directory_path: str, domain: str)`
Publish a local directory to the network under a specific domain.
```python
await client.search.deploy_proxy("/path/to/build", "my-app.feedo")
```

### `unpin(cid: str)`
Remove a pinned deployment from the proxy.
```python
await client.search.unpin("Qm...")
```

### `get_stats()`
Retrieve network statistics.
```python
stats = await client.search.get_stats()
```

---

## Consensus Module (`client.consensus`)

The Consensus module manages identity (DIDs), naming (.feedo domains), and grants.

### `resolve_name(name: str)`
Resolve a `.feedo` domain to its underlying CID (IPFS hash).
```python
info = await client.consensus.resolve_name("my-app.feedo")
print(info['cid'])
```

### `register_did(pubkey_hex: str, signature_hex: str)`
Register a new Decentralized Identifier.
```python
await client.consensus.register_did("0xabc...", "0xdef...")
```

### `get_did_balance(did: str)`
Check the token balance of a specific DID.
```python
balance = await client.consensus.get_did_balance("did:feedo:0xabc...")
```

### `register_name(name: str, did: str, cid: str, signature_hex: str)`
Register a new `.feedo` domain.
```python
await client.consensus.register_name("my-app", "did:feedo:...", "Qm...", "0x...")
```

### `update_name_cid(name: str, new_cid: str, signature_hex: str)`
Update the CID of an existing name.
```python
await client.consensus.update_name_cid("my-app", "QmNew...", "0x...")
```

---

## Storage Module (`client.storage`)

The Storage module acts as a decentralized file system.

### `upload_file(file_path: str, filename: str = "file")`
Upload a local file to the network.
```python
response = await client.storage.upload_file("./image.png")
print("Hash:", response['hash'])
```

### `download_file(hash_id: str) -> bytes`
Download a file from the network by its hash.
```python
raw_data = await client.storage.download_file("Qm...")
with open("downloaded.png", "wb") as f:
    f.write(raw_data)
```

### `ingest_json(payload: dict)`
Ingest structured JSON data directly into storage.
```python
await client.storage.ingest_json({"user": "alice", "action": "post"})
```

### `get_recent_files()`
Get a list of recently uploaded files.
```python
recent = await client.storage.get_recent_files()
```

## Error Handling

The SDK handles node failover automatically via the `NodeRouter`. However, if all seed nodes are unreachable, or if a specific network validation error occurs, the SDK will raise an exception. It is highly recommended to wrap network calls in `try/except` blocks:

```python
try:
    results = await client.search.query("DeFi protocols")
except Exception as e:
    print(f"Feedo Protocol Error: {e}")
```

## Response Structures

All responses are returned as native Python dictionaries matching the JSON schema of the Feedo Protocol. For example, a search result typically contains:
- `id`: Unique document identifier
- `score`: Semantic similarity score
- `metadata`: Associated metadata dictionary
- `content`: The raw text content

## Contributing

We welcome contributions to the Feedo Protocol SDK! 
GitHub Repository: [https://github.com/Ashixi/feedo-sdk](https://github.com/Ashixi/feedo-sdk)

1. Fork the repository.
2. Create your feature branch (`git checkout -b feature/amazing-feature`).
3. Commit your changes (`git commit -m 'Add some amazing feature'`).
4. Push to the branch (`git push origin feature/amazing-feature`).
5. Open a Pull Request.

## License

Apache License 2.0
