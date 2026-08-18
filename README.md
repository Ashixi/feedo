# Feedo Protocol

> ## Beta — Free for Everyone
>
> Feedo is currently in open beta. **Everything is free** — no payments, no tokens.
> We are actively working on the tokenomics layer, which is expected to be ready **within about a month**.
> Until then, feel free to use the network as much as you need — we just ask that you exercise fair use and be reasonable with the storage you consume.

---

> **We're building what everyone else only dreamed about.**
>
> **Feedo is the first fully decentralized search engine.**
>
> No central servers. No censorship. No filter bubbles controlled by a single company.
> We're destroying Web2's grip on information — one search query at a time.

---

## Hackathon Partners

Feedo is proud to be the official **Decentralized Hosting Partner** for global developer communities.

### CodeStorm 2026
We are currently powering the infrastructure for [CodeStorm 2026](https://codestorm-week2-2026.devfolio.co/overview). Over a thousand developers are building the future of the web on our nodes.

### How to publish your hackathon project (Quick Guide)
Are you participating in a hackathon and want to deploy your project to the Feedo network? It takes less than 3 seconds!

1. Install the Feedo Developer CLI.
2. Initialize your project (`feedo init`).
3. Deploy your site to the decentralized network (`feedo deploy`).

For the full setup and deployment guide, please visit our **[Feedo SDK Repository (Developer CLI)](https://github.com/Ashixi/feedo-sdk)**.

---

## The Problem

Today, the internet is controlled by three or four massive corporations.
They decide what you see, what you don't see, and who gets to exist online.
You can be deplatformed, shadowbanned, or wiped from the index not because you broke a law, but because **they simply didn't like it**.

Web3 started with a beautiful dream. The plan was right. True digital freedom.
But somewhere along the way, we took a wrong turn.
We got addicted to the money.
Tokens, speculation, gambling on memes while the one thing that actually matters was left behind.
**Search. Discovery. The ability to find anything.**

Think about it: we have decentralized money (Bitcoin), decentralized contracts (Ethereum), decentralized storage (IPFS) — but when was the last time you **searched** for something on a decentralized network? You can't. The search box still belongs to them.

That changes now.

**Feedo is how we fix Web3.**
With a search engine that nobody controls, nobody censors, and nobody can shut down.

The dream was never about the money.
It was about freedom.
We're bringing it back.

---

## How It Works

Feedo is built on three independent layers that work together as a single search engine — without a single central server.

### Consensus Layer (Rust)
A P2P network of nodes that agree on who owns what. Names, content hashes, and identity records are validated through a PBFT consensus protocol with a reputation-based rotating committee. No single node controls the truth.

**Key features**: PBFT consensus, DID identity system, DNS-like name resolution, on-chain treasury via `PporTreasury.sol` on Polygon, 25-node testnet verified.

### Storage Layer (Rust)
All content — websites, social posts, profiles, and arbitrary files — is stored using Reed-Solomon erasure coding. Every file is split into data shards + parity shards and distributed across the Kademlia DHT. If nodes go offline, the network self-heals and rebuilds lost shards automatically.

**Key features**: Erasure coding (30+15), Kademlia DHT storage, proactive self-healing, TTL-based garbage collection, censorship-resistant by design.

### Search Layer (Python)
Content is converted into dense vector embeddings using machine learning models. These vectors are stored locally and indexed for semantic search — meaning you find what you *mean*, not just what you *type*. Multiple search nodes form a federated network: each node knows which semantic clusters live where, and queries are routed intelligently without a central coordinator.

**Key features**: Vector semantic search (384-dim embeddings), CLIP image embeddings, federated P2P search via KMeans centroids, LanceDB for local vector storage, real-time indexing via WebSocket pub/sub.

---

**Together, these three layers form a complete search engine with no central authority, no single point of failure, and no censorship.**

---

## Repository Structure

```
feedo/
├── microservices/
│   ├── consensus-node/        # PBFT consensus & name resolution (Rust)
│   ├── storage-node/          # Erasure-coded P2P storage (Rust)
│   └── search-node/           # Vector semantic search engine (Python)
├── contracts/                 # PporTreasury.sol (Polygon smart contract)
└── feedo_explorer/            # Flutter cross-platform admin & search app
```

---

## Documentation

Each microservice has a documentation suite covering technical architecture, node operations, and production deployment.

### Consensus Node (Rust)

| Document | Audience | Description |
|----------|----------|-------------|
| [Technical Docs](microservices/consensus-node/CONSENSUS_DOCS.md) | Developers | Architecture, PBFT consensus, modules, API, testing |
| [Operator Guide](microservices/consensus-node/CONSENSUS_OPERATOR.md) | Node operators | Prerequisites, config, monitoring, troubleshooting, upgrades |
| [Deployment Guide](microservices/consensus-node/CONSENSUS_DEPLOY.md) | DevOps | Zero-config bare-metal deployment via `install.sh`, systemd, hardening |
| [Roadmap](microservices/consensus-node/CONSENSUS_ROADMAP.md) | Everyone | Scaling plan from 25 to 10,000+ nodes |

### Storage Node (Rust)

| Document | Audience | Description |
|----------|----------|-------------|
| [Technical Docs](microservices/storage-node/STORAGE_DOCS.md) | Developers | Architecture, erasure coding, P2P protocol, modules, API |
| [Operator Guide](microservices/storage-node/STORAGE_OPERATOR.md) | Node operators | Quick start, quotas, monitoring, troubleshooting, upgrades |
| [Deployment Guide](microservices/storage-node/STORAGE_DEPLOY.md) | DevOps | Zero-config bare-metal deployment via `install.sh`, systemd, hardening |
| [Roadmap](microservices/storage-node/STORAGE_ROADMAP.md) | Everyone | 5-phase scaling plan (Phase 1 ✅ done) |

### Search Node (Python)

| Document | Audience | Description |
|----------|----------|-------------|
| [Technical Docs](microservices/search-node/SEARCH_DOCS.md) | Developers | Architecture, vector search, federated search, modules, API |
| [Operator Guide](microservices/search-node/SEARCH_OPERATOR.md) | Node operators | Prerequisites, config, monitoring, troubleshooting, upgrades |
| [Deployment Guide](microservices/search-node/SEARCH_DEPLOY.md) | DevOps | Zero-config bare-metal deployment via `install.sh`, systemd, hardening |
| [Roadmap](microservices/search-node/SEARCH_ROADMAP.md) | Everyone | 5-phase scaling plan (Phase 1 ✅ done) |

---

## Identity

Feedo identity is wallet-native — there are no usernames or passwords.

- **DID = your wallet address** (`did:feedo:0x…`). Connect any EIP-6963 wallet (MetaMask, Coinbase Wallet, Rabby, Trust, Brave, Phantom, OKX…).
- **Register once** by signing `feedo register <did>` — you receive 500,000 free credits.
- **Usage key** — a separate key that signs requests but can't move funds, so your wallet's private key never leaves your wallet (or a server).

Three ways to create an identity:
1. **Website** — open [https://feedo.ink/identity.html](https://feedo.ink/identity.html), connect a wallet, register, and generate a usage key in one flow.
2. **CLI** — `feedo init` (creates a wallet + registers the DID), then `feedo usage-key` + `feedo delegate`.
3. **SDK** — `registerDid` / `register_did`, plus delegated mode via `usageKey` / `usage_key`.

See the [SDK docs](sdk/README.md) for the full usage-key & delegation reference.

---

## Tests

All three core nodes have integration tests covering real P2P scenarios.

```bash
# Consensus — 25-node PBFT test
cd microservices/consensus-node
cargo test --test integration_test_25

# Storage — erasure coding + DHT test
cd microservices/storage-node
cargo test --test integration_test

# Search — publish + query + relevance test
cd microservices/search-node
python tests/full_cycle_test.py
```

| Test | Status | What it validates |
|------|--------|-------------------|
| 25-node consensus | ✅ Passed | PBFT, epoch rotation, fault tolerance (kill 5/25 nodes) |
| Storage integration | ✅ Passed | Upload, download, delete, erasure coding |
| Search pipeline | ✅ Passed | Publish site → index → search → relevance check |

---

## Roadmap

Detailed roadmaps for each layer are available in their respective directories:

- [Consensus Node Roadmap](microservices/consensus-node/CONSENSUS_ROADMAP.md) — scaling from 25 to 10,000+ nodes
- [Storage Node Roadmap](microservices/storage-node/STORAGE_ROADMAP.md) — from 10 GB to unlimited storage, cloud storage protocol
- [Search Node Roadmap](microservices/search-node/SEARCH_ROADMAP.md) — from full replication to semantic sharding, GPU inference, DuckDuckGo-level quality

---

## Community

Join our Discord server to ask questions, meet the team, or apply for the technical co-founder role! 

**[Join the Feedo Discord](https://discord.gg/9sktH22ZN)**

---

## Contact

- 🐙 GitHub — [Feedo SDK](https://github.com/Ashixi/feedo-sdk)
- 🌐 Website — [feedo.ink](https://feedo.ink)
- 💬 Discord — [Join the Feedo Discord](https://discord.gg/9sktH22ZN)
- 𝕏 X — [@andrii_shumko](https://x.com/andrii_shumko)
- ✉️ Email — [andrii@feedo.ink](mailto:andrii@feedo.ink)

---

## Support the Project

Feedo is fully open-source and community-funded. No VCs. No tokens. Just builders.

- [Buy Me a Coffee](https://buymeacoffee.com/andriishumko)


---

## License

Apache 2.0 License — see [LICENSE](LICENSE) for details.
