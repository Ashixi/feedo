# Feedo Protocol SDKs & CLI

Welcome to the official SDK and Developer Tools repository for the [Feedo Protocol](https://github.com/Ashixi/feedo).

Feedo is a decentralized network designed for secure storage, semantic search, and decentralized identity. This repository provides everything you need to build Web3 applications, social networks, and AI agents on top of the Feedo Network.

## Available SDKs

Choose the SDK that best fits your environment:

### 1. [TypeScript / JavaScript SDK](./typescript/README.md)
The primary SDK for building Web3 dApps, Node.js backends, React, and React Native applications.
- **NPM Package**: [`feedo-protocol-sdk`](https://www.npmjs.com/package/feedo-protocol-sdk)
- **Key Features**: Dynamic routing, E2EE file uploads, Semantic Search, Identity Management.

### 2. [Python SDK](./python/README.md)
A fully asynchronous Python SDK built on `httpx` and `asyncio`, optimized for AI Agents, Data Pipelines, and Backend services.
- **PyPI Package**: [`feedo-sdk`](https://pypi.org/project/feedo-sdk/)
- **Key Features**: High-performance async API, ECIES Encryption, EIP-191 Auth.

---

## Command Line Interface (CLI)

### 3. [Feedo CLI](./cli/README.md)
A powerful command-line tool for deploying static websites, managing decentralized domains (`.feedo`), and interacting with the network without writing code.
- **NPM Package**: [`feedo-sdk`](https://www.npmjs.com/package/feedo-sdk) (Wait, note: CLI package is published as `feedo-sdk` on npm)
- **Commands**:
  - `feedo login`: Authenticate with your private key.
  - `feedo deploy <dir>`: Upload a directory to Feedo Storage.
  - `feedo balance`: Check your network credits.

---

## Core Capabilities

By using these SDKs, developers can easily interact with all three layers of the Feedo architecture:

1. **Storage Node (`client.storage`)**
   - Decentralized, IPFS-like file storage.
   - Built-in End-to-End Encryption (AES-256-GCM + ECIES).
   - "Gas Sponsorship" & Delegated uploads support.

2. **Consensus Node (`client.consensus`)**
   - **DID Registration**: Create and manage Decentralized Identifiers.
   - **Naming Service**: Register `.feedo` domains and link them to CIDs.
   - **Access Control**: Grant other DIDs access to your private files.

3. **Search Node (`client.search`)**
   - **Semantic Search**: Native AI vector embeddings for text search.
   - **Indexing**: Make public or private documents searchable.
   - **Web2 Gateway**: HTTP gateway for fast content retrieval.

## Identity (DID & Usage Key)

Your **identity is your wallet** — your DID is simply `did:feedo:0x<your-wallet-address>`.

- **Register** once by signing `feedo register <did>` (`registerDid` / `register_did`).
- For server SDKs, use a separate **usage key** so your funding key never leaves your wallet. See the "Usage Key & Delegation" section in each SDK's README.
- You can create an identity + usage key without code at [https://feedo.ink/identity.html](https://feedo.ink/identity.html) (any EIP-6963 wallet: MetaMask, Coinbase Wallet, Rabby, …).

Learn more:
- [TypeScript SDK — Usage Key & Delegation](./typescript/README.md#usage-key--delegation-server-side)
- [Python SDK — Usage Key & Delegation](./python/README.md#usage-key--delegation-server-side)
- [CLI — `feedo usage-key` / `feedo delegate`](./cli/README.md#feedo-usage-key)

## Important Note for New Developers ⚠️

Before you can upload files or perform any write operations using these SDKs, **you must first register your DID**.
Registering your DID generates your identity on the blockchain and grants you the initial credits (500,000) required for storage.

Please refer to the `README.md` inside your specific language's folder for detailed instructions on how to register your DID.

---

## Pricing & Economics (Testnet vs Mainnet)

**Currently, the network is in Testnet/Early Access mode and is completely FREE.**
Upon registering a new DID, you receive 500,000 test credits, which allows you to upload files and perform semantic searches without any real-world cost.

**Future Mainnet Pricing:**
As the network scales and onboards enterprise clients, the Feedo Protocol will transition to a sustainable paid model. The target pricing structure is designed to be highly competitive for Web3 and AI developers:

- **Decentralized Storage:** ~$20.00 per Terabyte (TB)
- **Vector Search / Indexing:** ~$5.00 per 10,000 semantic search queries

*(Note: Pricing will be managed via on-chain tokenomics and smart contracts, allowing developers to pay via stablecoins or the native Feedo token).*

---

## Contributing

We welcome contributions! Please feel free to submit issues, fork the repository and send pull requests.

## License

Apache License 2.0
