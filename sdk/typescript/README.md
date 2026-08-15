# Feedo Protocol TypeScript SDK

The official Developer SDK for interacting with the Feedo Protocol.

Feedo is a decentralized network consisting of Search, Consensus, and Storage nodes. This SDK provides a unified interface to interact with all layers of the Feedo Protocol from any JavaScript or TypeScript environment (Web3 dApps, Node.js backends, React Native).

## Features

- **Dynamic Node Routing:** The SDK automatically pings seed nodes and routes your requests to the fastest available node. If a node goes offline, the router instantly falls back to another healthy node.
- **TypeScript Native:** Fully typed API for excellent developer experience and autocomplete.
- **Modular Design:** Divided into `search`, `consensus`, and `storage` modules for clean architecture.
- **End-to-End Encryption:** Built-in E2EE using AES-256-GCM and ECIES for private file storage.
- **DID Authentication:** Every request is signed with your Ethereum wallet, verified by the Consensus and Storage nodes.

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

// Without authentication (read-only operations)
const feedo = new FeedoClient();
```

To perform authenticated operations (upload, index, search private files), provide your wallet's private key:

```typescript
import { FeedoClient } from 'feedo-protocol-sdk';
import { ethers } from 'ethers';

const wallet = ethers.Wallet.createRandom();

const feedo = new FeedoClient({
    privateKey: wallet.privateKey,
    storageSeeds: ['https://storage.feedo.network'],
    consensusSeeds: ['https://consensus.feedo.network'],
    searchSeeds: ['https://search.feedo.network'],
});
```

*(Optional) You can provide your own seed nodes if you are running a private/local cluster:*
```typescript
const feedo = new FeedoClient({
    searchSeeds: ['http://localhost:8000'],
    consensusSeeds: ['http://localhost:3000'],
    storageSeeds: ['http://localhost:3001'],
    privateKey: '0x...'
});
```

---

## ⚠️ Important: Registering Your DID

Before you can perform **any write operations** (uploading files, indexing documents, granting access), you **MUST** register your Decentralized Identifier (DID) on the Feedo Consensus network.

Registering your DID creates your identity on the blockchain and grants you the initial credits (500,000 credits) needed to pay for storage and compute. Without a registered DID, the storage nodes will reject your uploads due to "insufficient balance".

You only need to do this **once per wallet**.

> **No-code option:** create your identity in the browser at [https://feedo.ink/identity.html](https://feedo.ink/identity.html) — connect any wallet, register the DID, and generate a usage key in one flow.

```typescript
import { ethers } from 'ethers';

// Your DID is your wallet address
const did = `did:feedo:${wallet.address}`;

// 1. Sign the canonical registration message to prove wallet ownership
const sig = await wallet.signMessage(`feedo register ${did}`);

// 2. Register the DID on the network
await feedo.consensus.registerDid(wallet.signingKey.publicKey, sig);

console.log("DID Registered successfully! You can now upload files.");
```

---

## Quick Start — Full E2EE Flow

```typescript
import { FeedoClient } from 'feedo-protocol-sdk';
import { ethers } from 'ethers';

const wallet = ethers.Wallet.createRandom();

const feedo = new FeedoClient({
    privateKey: wallet.privateKey,
    storageSeeds: ["http://localhost:3001"],
    consensusSeeds: ["http://localhost:3000"],
    searchSeeds: ["http://localhost:8000"],
});

// 1. Register your DID on the network
const sig = await wallet.signMessage('register');
await feedo.consensus.registerDid(wallet.signingKey.publicKey, sig);

// 2. Upload an encrypted private file and index it for search
const text = "My secret post content";
const hashId = await feedo.uploadPrivateFile(
    Buffer.from(text, 'utf-8'),
    undefined,   // grantee (undefined = self)
    true,        // index for search
    { app_id: 'com.myapp', type: 'post' }
);

// 3. Search your private files
const results = await feedo.search.search('secret', 10, true, 'all', 0, 'com.myapp');
console.log(results);
```

---

## Search Module (`feedo.search`)

The Search module handles semantic queries, document vectorization, and Web2/Web3 gateways.

### `search(queryText, limit?, federated?, itemType?, offset?, appId?, searchType?, imageUrl?)`
Perform a semantic search across the network. By default, this performs text-to-text semantic search.
To search for an image using text, set `searchType` to `"image"`. To search for an image using another image, provide the `imageUrl` and set `searchType` to `"image"`.
```typescript
// Text-to-text search
const response = await feedo.search.search("DeFi protocols", 5, true, "post", 0, "SocialApp1");

// Text-to-image search (e.g. for a Fashion app)
const textToImage = await feedo.search.search("red dress", 5, true, "image", 0, undefined, "image");

// Image-to-image search
const imageToImage = await feedo.search.search("", 5, true, "image", 0, undefined, "image", "https://example.com/dress.jpg");
console.log(response.results);
```

### `getDocuments(limit?, offset?, itemType?, appId?)`
Fetch a feed of the latest indexed documents without semantic search.
```typescript
const feed = await feedo.search.getDocuments(50, 0, "post", "SocialApp1");
```

### `indexDocument(content, metadata?)`
Index a public document into the vector database.
```typescript
await feedo.search.indexDocument("Bitcoin is a decentralized cryptocurrency.", { type: "post" });
```

### `indexPrivateDocument(hashId, plaintext, metadata?)`
Index a **private** document (requires `privateKey` to sign the request).
```typescript
await feedo.search.indexPrivateDocument(hashId, "My private content", { app_id: "com.myapp" });
```

### `getStats()`
Retrieve network statistics.
```typescript
const stats = await feedo.search.getStats();
```

---

## Consensus Module (`feedo.consensus`)

The Consensus module interacts with the Rust-based blockchain layer to manage identity (DIDs), naming (.feedo domains), and grants.

### `registerDid(publicKeyHex, signatureHex)`
Register a new Decentralized Identifier on the network. Uses `wallet.signingKey.publicKey` (ethers v6).
```typescript
const sig = await wallet.signMessage('register');
await feedo.consensus.registerDid(wallet.signingKey.publicKey, sig);
```

### `resolveName(name)`
Resolve a `.feedo` domain to its underlying CID and owner.
```typescript
const info = await feedo.consensus.resolveName("my-app.feedo");
console.log(info.cid);
```

### `getDidBalance(did)`
Check the credit balance of a specific DID.
```typescript
const balance = await feedo.consensus.getDidBalance("did:feedo:0xabc...");
console.log(balance.balance_credits);
```

### `registerName(name, did, cid, signatureHex)`
Register a new `.feedo` domain and link it to a CID.
```typescript
await feedo.consensus.registerName("my-app", "did:feedo:...", "Qm...", "0x...");
```

### `grantFileAccess(fileHash, granteeDid, encryptedSymKey, publicKey, signature)`
Grant access to an encrypted file for another DID.
```typescript
await feedo.consensus.grantFileAccess(hashId, targetDid, encSymKey, myPubKey, sig);
```

---

## Storage Module (`feedo.storage`)

The Storage module acts as an IPFS-like decentralized file system.

### `uploadFile(file, filename?)`
Upload a file buffer or Blob to the network. Returns the file hash ID.
```typescript
const fileBuffer = fs.readFileSync('./image.png');
const hashId = await feedo.storage.uploadFile(fileBuffer, 'image.png');
console.log("File Hash:", hashId);
```

### `downloadFile(hash)`
Download a file from the network by its hash.
```typescript
const buffer = await feedo.storage.downloadFile("abc123...");
```

### `getRecentFiles()`
Get a list of recently uploaded public files.
```typescript
const recent = await feedo.storage.getRecentFiles();
```

---

## E2EE Private Files (End-to-End Encryption)

The SDK provides built-in End-to-End Encryption using AES-256-GCM and ECIES. You need to provide a `privateKey` in the client config to use these features.

### `uploadPrivateFile(fileBuffer, granteePublicKeyHex?, indexForSearch?, metadata?)`
Uploads a file securely. The file is AES-encrypted on the client, and the symmetric key is ECIES-encrypted for the grantee.
```typescript
const fileBuffer = Buffer.from("My secret diary entry");
const hashId = await feedo.uploadPrivateFile(
    fileBuffer,
    undefined,  // grantee (undefined = grant to self)
    true,       // index for search
    { app_id: "com.myapp", type: "note" }
);
console.log("Encrypted File Hash:", hashId);
```

### `downloadPrivateFile(hashId)`
Downloads and automatically decrypts a private file (if your DID has access).
```typescript
const decryptedBuffer = await feedo.downloadPrivateFile("abc123...");
console.log(decryptedBuffer.toString('utf-8'));
```

#### How it works under the hood:
1. **Client-Side Encryption:** Your file is encrypted locally using AES-256-GCM with a random symmetric key.
2. **Secure Storage:** The encrypted blob is uploaded to the **Storage Node** (which cannot read the content).
3. **Access Management:** The symmetric key is ECIES-encrypted using the grantee's public key and stored on the **Consensus Node**.
4. **Private Vectorization:** If `indexForSearch` is true, the plaintext is sent to the **Search Node** for vectorization. The plaintext is immediately discarded after embedding.

---

## DID Authentication

All write operations require a signed `X-Feedo-*` header set. The SDK handles this automatically when you provide a `privateKey`:

```
X-Feedo-DID:       did:feedo:0xYourAddress
X-Feedo-Timestamp: 1722345678901
X-Feedo-Signature: 0x<ECDSA signature of "FeedoAction:METHOD:PATH:TIMESTAMP">
```

---

## Usage Key & Delegation (server-side)

Your DID **is** your wallet address — the **funding key** that holds your credits/funds. For server SDKs (AnythingLLM, Dify, backends), never put the funding key in the environment. Instead, use a separate **usage key** that only signs requests and can never move funds.

| Key | What it is | Holds funds? |
|---|---|---|
| **Funding key** | Your wallet. `did:feedo:<address>` | yes |
| **Usage key** | Separate key that signs requests | no — only spends your credits |

### Getting a usage key

**Option A — Website (recommended).** Open [https://feedo.ink/identity.html](https://feedo.ink/identity.html), connect any wallet (EIP-6963: MetaMask, Coinbase Wallet, Rabby, Trust, Brave, Phantom, OKX…), and click **Generate usage key**. The site generates a random usage key in the browser and registers the delegation with a single wallet signature. Copy the printed private key into your server env.

**Option B — SDK / CLI (deterministic).** Derive it from your wallet key with HMAC:

```typescript
import { FeedoCrypto } from 'feedo-protocol-sdk';

const usage = FeedoCrypto.deriveUsageKey(wallet.privateKey);
console.log(usage.address, usage.privateKey);
```

Then register the delegation once — the wallet signs `feedo delegate usage to <usage_address>`:

```
POST /did/delegate  { did, usage_key, signature }
```

Or run `feedo delegate` from the CLI.

### Delegated mode

```typescript
const feedo = new FeedoClient({
    usageKey: usage.privateKey,   // the usage key (NOT your funding key)
    did: 'did:feedo:0x...',       // your wallet DID (owner)
    consensusSeeds: ['https://consensus.feedo.network'],
    searchSeeds: ['https://search.feedo.network'],
});
```

Requests are signed with the usage key and declare the owner DID; nodes resolve the delegation automatically.

---

## Error Handling

The SDK handles node failover automatically via the `NodeRouter`. Wrap network calls in `try/catch`:

```typescript
try {
    const results = await feedo.search.search("DeFi protocols");
} catch (error: any) {
    console.error("Feedo Protocol Error:", error.message);
}
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
