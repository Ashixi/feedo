# Feedo Protocol 🚀

> **We're building what everyone else only dreamed about.**
>
> **Feedo is the first fully decentralized search engine.**
>
> No central servers. No censorship. No filter bubbles controlled by a single company.
> We're destroying Web2's grip on information — one search query at a time.

---

## 🌍 The Problem

Today, the internet is controlled by three or four massive corporations.
They decide what you see, what you don't see, and who gets to exist online.
You can be deplatformed, shadowbanned, or wiped from the index — not because you broke a law, but because **they simply didn't like it**.

Web3 started with a beautiful dream. The plan was right. True digital freedom.
But somewhere along the way, we took a wrong turn.
We got addicted to the money.
Tokens, speculation, gambling on memes — while the one thing that actually matters was left behind.
**Search. Discovery. The ability to find anything.**

Think about it: we have decentralized money (Bitcoin), decentralized contracts (Ethereum), decentralized storage (IPFS) — but when was the last time you **searched** for something on a decentralized network? You can't. The search box still belongs to them.

That changes now.

**Feedo is how we fix Web3.**
With a search engine that nobody controls, nobody censors, and nobody can shut down.

The dream was never about the money.
It was about freedom.
We're bringing it back.

---

## 🏗️ How It Works

Feedo is built on three independent layers that work together as a single search engine — without a single central server.

### 🔗 Consensus Layer (Rust)
A P2P network of nodes that agree on who owns what. Names, content hashes, and identity records are validated through a PBFT consensus protocol with a reputation-based rotating committee. No single node controls the truth.

**Key features**: PBFT consensus, DID identity system, DNS-like name resolution, on-chain treasury via `PporTreasury.sol` on Polygon, 25-node testnet verified.

### 💾 Storage Layer (Rust)
All content — websites, social posts, profiles, and arbitrary files — is stored using Reed-Solomon erasure coding. Every file is split into data shards + parity shards and distributed across the Kademlia DHT. If nodes go offline, the network self-heals and rebuilds lost shards automatically.

**Key features**: Erasure coding (30+15), Kademlia DHT storage, proactive self-healing, TTL-based garbage collection, censorship-resistant by design.

### 🔍 Search Layer (Python)
Content is converted into dense vector embeddings using machine learning models. These vectors are stored locally and indexed for semantic search — meaning you find what you *mean*, not just what you *type*. Multiple search nodes form a federated network: each node knows which semantic clusters live where, and queries are routed intelligently without a central coordinator.

**Key features**: Vector semantic search (384-dim embeddings), CLIP image embeddings, federated P2P search via KMeans centroids, LanceDB for local vector storage, real-time indexing via WebSocket pub/sub.

---

**Together, these three layers form a complete search engine with no central authority, no single point of failure, and no censorship.**

---

## 📂 Repository Structure

```
feedo/
├── microservices/
│   ├── consensus-node/        # PBFT consensus & name resolution (Rust)
│   ├── storage-node/          # Erasure-coded P2P storage (Rust)
│   ├── search-node/           # Vector semantic search engine (Python)
│   ├── feedo-ingester/        # Nostr bridge — real-time data ingestion
│   ├── social-node/           # Social feed & profile aggregation
│   └── feedo-algo/            # Background clustering & trending math
├── contracts/                 # PporTreasury.sol (Polygon smart contract)
├── feedo_sdk/                 # Client SDKs (js, python, rust, dart)
└── feedo_search_ui/           # Flutter cross-platform search app
```

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Git

### 1. Clone & Configure
```bash
git clone https://github.com/Ashixi/feedo.git
cd feedo/microservices
cp .env.example .env.local
```

### 2. Start the Stack
```bash
docker-compose up -d
```
This starts all three core nodes — consensus, storage, and search — plus the social node, ingester, and search UI.

### 3. Verify
```bash
# Test search
curl "http://localhost:8000/query?text=test"

# Test name resolution
curl "http://localhost:3000/resolve/test.feedo"

# Check node stats
curl "http://localhost:8000/explorer/stats"
```

---

## 🧪 Tests

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

## 🗺️ Roadmap

Detailed roadmaps for each layer are available in their respective directories:

- [Consensus Node Roadmap](microservices/consensus-node/CONSENSUS_ROADMAP.md) — scaling from 25 to 10,000+ nodes
- [Storage Node Roadmap](microservices/storage-node/STORAGE_ROADMAP.md) — from 10 GB to unlimited storage, cloud storage protocol
- [Search Node Roadmap](microservices/search-node/SEARCH_ROADMAP.md) — from full replication to semantic sharding, GPU inference, DuckDuckGo-level quality

---

## 🤝 Support the Project

Feedo is fully open-source and community-funded. No VCs. No tokens. Just builders.

- ☕ [Buy Me a Coffee](https://buymeacoffee.com/andriishumko)
- 💎 [Giveth](https://giveth.io/project/feedo)
- 🌐 [Open Collective](https://opencollective.com/feedo)
- 🔶 Gitcoin Grants — coming soon (building community first)

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
