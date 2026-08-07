# Feedo Protocol TypeScript SDK

The official Developer SDK for interacting with the Feedo Protocol.

Feedo is a decentralized network consisting of Search, Consensus, and Storage nodes. This SDK provides a unified interface to interact with all layers of the Feedo Protocol from any JavaScript or TypeScript environment (Web3 dApps, Node.js backends, React Native).

## Features

- **Dynamic Node Routing:** The SDK automatically pings seed nodes and routes your requests to the fastest available node. If a node goes offline, the router instantly falls back to another healthy node.
- **TypeScript Native:** Fully typed API for excellent developer experience and autocomplete.
- **Modular Design:** Divided into `search`, `consensus`, and `storage` modules for clean architecture.

## Installation

```bash
npm install feedo-protocol-sdk
# or
yarn add feedo-protocol-sdk
# or
pnpm add feedo-protocol-sdk
```

## Initialization

You do not need to specify URLs for the nodes. The SDK comes with pre-configured seed nodes and uses a `NodeRouter` to find the fastest connection automatically.

```typescript
import { FeedoClient } from 'feedo-protocol-sdk';

const feedo = new FeedoClient();
```

*(Optional) You can provide your own seed nodes if you are running a private cluster:*
```typescript
const feedo = new FeedoClient({
    searchSeeds: ['https://my-search.node'],
    consensusSeeds: ['https://my-consensus.node'],
    storageSeeds: ['https://my-storage.node']
});
```

---

## Search Module (`feedo.search`)

The Search module handles semantic queries, document vectorization, and Web2/Web3 gateways.

### `search(queryText: string, limit?: number, federated?: boolean, itemType?: string, offset?: number, appId?: string)`
Perform a semantic search across the network, optionally filtering by item type or application ID.
```typescript
// Example: Search only within 'post' items created by 'SocialApp1'
const response = await feedo.search.search("DeFi protocols", 5, true, "post", 0, "SocialApp1");
console.log(response.results);
```

### `getDocuments(limit?: number, offset?: number, itemType?: string, appId?: string)`
Fetch a feed of the latest indexed documents without semantic search, with optional filtering.
```typescript
const feed = await feedo.search.getDocuments(50, 0, "post", "SocialApp1");
```

### `indexDocument(content: string, metadata?: Record<string, any>)`
Index a raw document into the vector database. The `metadata.type` property automatically maps to the backend `item_type` for filtering.
```typescript
await feedo.search.indexDocument("Bitcoin is a decentralized cryptocurrency.", { type: "post", source: "wiki" });
```

### `deployProxy(directoryPath: string, domain: string)`
Publish a local directory to the network under a specific domain.
```typescript
await feedo.search.deployProxy("./build", "my-app.feedo");
```

### `unpin(cid: string)`
Remove a pinned deployment from the proxy.
```typescript
await feedo.search.unpin("Qm...");
```

### `getStats()`
Retrieve network statistics.
```typescript
const stats = await feedo.search.getStats();
```

---

## Consensus Module (`feedo.consensus`)

The Consensus module interacts with the Rust-based blockchain layer to manage identity (DIDs), naming (.feedo domains), and grants.

### `resolveName(name: string)`
Resolve a `.feedo` domain to its underlying CID (IPFS hash) and owner.
```typescript
const info = await feedo.consensus.resolveName("my-app.feedo");
console.log(info.cid);
```

### `registerDid(pubkeyHex: string, signatureHex: string)`
Register a new Decentralized Identifier on the network.
```typescript
await feedo.consensus.registerDid("0xabc...", "0xdef...");
```

### `getDidBalance(did: string)`
Check the token balance of a specific DID.
```typescript
const balance = await feedo.consensus.getDidBalance("did:feedo:0xabc...");
```

### `registerName(name: string, did: string, cid: string, signatureHex: string)`
Register a new `.feedo` domain and link it to a CID.
```typescript
await feedo.consensus.registerName("my-app", "did:feedo:...", "Qm...", "0x...");
```

### `updateNameCid(name: string, newCid: string, signatureHex: string)`
Update the CID of an existing name.
```typescript
await feedo.consensus.updateNameCid("my-app", "QmNew...", "0x...");
```

---

## Storage Module (`feedo.storage`)

The Storage module acts as an IPFS-like decentralized file system.

### `uploadFile(file: any, filename?: string)`
Upload a file buffer or Blob to the network.
```typescript
const fileBuffer = fs.readFileSync('./image.png');
const response = await feedo.storage.uploadFile(fileBuffer, 'image.png');
console.log("File Hash:", response.hash);
```

### `downloadFile(hash: string)`
Download a file from the network by its hash.
```typescript
const buffer = await feedo.storage.downloadFile("Qm...");
```

### `ingestJson(payload: any)`
Ingest structured JSON data directly into the storage layer.
```typescript
await feedo.storage.ingestJson({ user: "alice", action: "post", content: "Hello Feedo!" });
```

### `getRecentFiles()`
Get a list of recently uploaded public files.
```typescript
const recent = await feedo.storage.getRecentFiles();
```

---

## E2EE Private Files (End-to-End Encryption)

The SDK provides built-in End-to-End Encryption using AES-GCM and ECIES. You can seamlessly encrypt files, store them on the decentralized network, and manage access via the Consensus Node.

### `uploadPrivateFile(fileBuffer: Buffer, granteePublicKeyHex?: string, indexForSearch?: boolean)`
Uploads a file securely. The file is AES-encrypted on the client, and the symmetric key is ECIES-encrypted for the grantee.
```typescript
// Upload a private file for yourself and index it in the Search Node for private querying
const fileBuffer = Buffer.from("My secret diary entry");
const hashId = await feedo.uploadPrivateFile(fileBuffer);
console.log("Encrypted File Hash:", hashId);
```

### `downloadPrivateFile(hashId: string)`
Downloads and automatically decrypts a private file (if your DID has access granted by the Consensus Node).
```typescript
const decryptedBuffer = await feedo.downloadPrivateFile("Qm...");
console.log(decryptedBuffer.toString('utf-8'));
```

#### How it works under the hood:
1. **Client-Side Encryption:** The SDK locally encrypts your file using AES-GCM. 
2. **Secure Storage:** The encrypted gibberish is uploaded to the **Storage Node** (which has no idea what the file contains).
3. **Access Management:** The AES symmetric key is asymmetrically encrypted (ECIES) using the receiver's public key and stored safely on the **Consensus Node**.
4. **Private Vectorization:** If `indexForSearch` is true, the plaintext is temporarily sent to the **Search Node**, which generates a vector embedding and *immediately deletes the plaintext*. This allows you to semantically search your private files without exposing the data.

## Error Handling

The SDK handles node failover automatically via the `NodeRouter`. However, if all seed nodes are unreachable, or if a specific network validation error occurs, the SDK will throw an exception. It is highly recommended to wrap network calls in `try/catch` blocks:

```typescript
try {
    const results = await feedo.search.query("DeFi protocols");
} catch (error: any) {
    console.error("Feedo Protocol Error:", error.message);
}
```

## Response Structures

The SDK is designed to return clean, typed objects. For example, resolving a `.feedo` name returns an object containing the CID and the owner's DID:

```typescript
interface NameResolution {
    cid: string;
    owner: string;
    isActive: boolean;
}
```

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
