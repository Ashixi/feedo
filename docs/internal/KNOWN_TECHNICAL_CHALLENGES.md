# Feedo Ecosystem: Known Technical Challenges & Risks

> **Audience**: Internal use, grant applications ("Risk Mitigation & Future Work" section).
> **Status**: Living document — updated as new challenges are discovered and mitigations developed.
> **Scope**: Technical/architectural problems — implementation, scaling, performance, security, data integrity.
> **Conceptual problems** (moderation, governance, economic model, legal liability, centralization vectors) are covered in [KNOWN_CHALLENGES.md](./KNOWN_CHALLENGES.md).

---

## 1. Data Storage Economics (Storage Node)

The current architecture utilizes Reed-Solomon Erasure Coding (30 data shards + 15 parity shards). This provides high reliability but introduces a 50% overhead for every file.

### 1.1 Lack of Garbage Collection (GC)

**Core Problem**: Currently, the `ttl_days` field is declared in `IngestPayload` but not enforced anywhere — no code deletes expired data. Storage grows unboundedly, consuming operator disk space indefinitely.

**Mitigation Roadmap**:
- Implement Proactive Garbage Collection (Phase 3): Automatically delete temporary content (e.g., `SocialPost` class) after the TTL expires unless it has been "pinned" via microtransactions.
- Default TTL policy: `Site` = indefinite, `SocialPost` = 30 days, `Profile` = 365 days, `Blob` = indefinite (paid).

### 1.2 Storage Cost Without Revenue

**Core Problem**: Storing data costs real money (disk space, bandwidth). Without financial incentives, node operators will not host other people's "heavy" files (websites, videos, images). The 50% Reed-Solomon overhead makes this worse — every 1 GB of user data costs the operator 1.5 GB of disk space.

**Mitigation Roadmap**: 📎 **Solution track exists** — see tokenomics plan (separate document). A pay-per-byte model via `PporTreasury.sol` will allow content creators to pay for storage, with node operators receiving rewards for disk space + bandwidth. Integration with the built-in Ledger and Polygon smart contracts is the economic foundation.

### 1.3 Free Rider Problem

**Core Problem**: Anyone can upload a file and have it distributed across the network as 45 shards — for free. The uploader pays nothing, while node operators bear the real costs of disk I/O, storage, and bandwidth. There is no rate-limiting or cost at the protocol level for uploads.

**Mitigation Roadmap**: 📎 **Solution track exists** — the tokenomics plan addresses this directly. Storage quotas per DID (enforced by the Ledger), pay-per-byte pricing, and credit consumption on upload will ensure that storage consumption is metered and paid for.

---

## 2. Data Reliability and "Blind" Persistence (Storage Node)

Currently, restoring lost shards only happens reactively (reactive self-healing).

### 2.1 Reactive Self-Healing Only

**Core Problem**: If nodes quietly leave the network (Network Churn), the system won't know about the lost shards until someone tries to download the file. If more than 15 shards disappear before a read operation, the file is lost forever.

**Mitigation Roadmap**:
- Proactive Healing (Phase 3): Implement background daemons on Storage Nodes that periodically ping the shards of their manifests. If the number of available shards drops below a critical threshold (e.g., < 35), the node automatically initiates re-encoding and redistribution.

### 2.2 Manifest Single Point of Failure

**Core Problem**: Manifests (which map file hashes to shard locations) are stored with `Quorum::One` — a single copy on one node. If that node goes offline, the file cannot be located even if all 45 shards are still available on other nodes.

**Mitigation Roadmap**:
- Increase the manifest quorum to `Quorum::Three` (Phase 3) to provide redundant access points for shard locations.
- On manifest creation, publish to at least 3 Kademlia peers.
- On manifest fetch, try multiple nodes from the Kademlia routing table.

---

## 3. Semantic Sharding Edge Cases (Search Node)

Semantic sharding based on KMeans is an innovative but experimental solution that requires fine-tuning under extreme conditions.

### 3.1 Cluster Imbalance (The Black Hole Effect)

**Core Problem**: If the network is flooded with content from a single niche (e.g., only Web3 projects), the vast majority of vectors will be routed to just a few nodes whose centroids are closest to that topic. These nodes will be overloaded, while others sit idle with empty shards.

**Mitigation Roadmap**:
- Spillover Mechanism: Enforce a maximum index size per node. If a node reaches its capacity, it delegates (spills over) the incoming vector to the next semantically closest node in the global map, distributing load more evenly.

### 3.2 Centroid Drift (Rebalancing Storm)

**Core Problem**: During rapid data ingestion, centroids may shift too frequently, triggering constant event-driven P2P traffic (`/p2p/handshake`) to update the `global_knowledge_map` across the network. This creates a "storm" of P2P messages.

**Mitigation Roadmap**:
- Dynamic Update Thresholds: Transition from a static `SHARD_CENTROID_UPDATE_THRESHOLD` (100 vectors) to a dynamic, logarithmic, or percentage-based threshold that scales with the size of the node's index, reducing P2P network spam.
- Debounce mechanism: no more than one handshake broadcast per 30 seconds, regardless of centroid drift.

---

## 4. Security & Trust Model Weaknesses

### 4.1 Trust-Based Vector Forwarding (Search Node)

**Core Problem**: In `crawler.py`, when a vector does not belong to the local shard, it is forwarded to another node via `POST /p2p/index_vector`. The receiving node **does not re-validate** `is_my_shard()` — it trusts the sender unconditionally. A malicious actor can spam any search node with arbitrary vectors that semantically belong elsewhere, effectively bypassing the sharding mechanism and bloating another node's index.

**Mitigation Roadmap**: ✅ **Solution identified** — add `is_my_shard()` re-validation on the receiving side in `/p2p/index_vector`. If a vector does not belong to the receiving node's shard, reject it (HTTP 406). Combine with rate limiting already present (200 req/s on `/p2p/index_vector`).

### 4.2 Fake Centroid Injection (Search Node)

**Core Problem**: Any node can send arbitrary centroids via `POST /p2p/handshake`. There is no cryptographic verification that the centroids were genuinely computed from real data. A malicious node could inject "strategic" centroids positioned to attract vectors for specific topics — performing a semantic man-in-the-middle attack on search queries.

**Mitigation Roadmap**: ✅ **Solution identified** — sign centroid payloads with the node's Ed25519 key (which search-node currently lacks). Add reputation tracking for centroid accuracy: if a node's centroids consistently produce poor search results (measured via feedback), reduce its weight in the `global_knowledge_map`. Short-term: rate-limiting and trust-based gradual adoption of new centroids.

### 4.3 Unauthenticated P2P Endpoints (Search Node)

**Core Problem**: Unlike `consensus-node` and `storage-node` which use libp2p with noise encryption and QUIC TLS 1.3, the `search-node` uses plain HTTP for all P2P communication. `/p2p/search`, `/p2p/index_vector`, and `/p2p/handshake` are unencrypted and unauthenticated. Any network intermediary can intercept, modify, or replay search traffic.

**Mitigation Roadmap**: ✅ **Solution identified** — deploy search-node behind a reverse proxy (nginx/Caddy) with Let's Encrypt TLS for HTTPS encryption. Update `PUBLIC_API_URL` to `https://...`. Long-term: consider migrating search-node P2P to libp2p for consistency with other microservices, or implement mutual TLS (mTLS) between search nodes.

### 4.4 Sybil Attack on Reputation (Consensus Node)

**Core Problem**: The reputation system in `ppor.rs` is tied to `NODE_WALLET_ADDRESS`. An attacker can generate thousands of Ethereum wallets, spawn thousands of consensus nodes, and have them all vote for each other — artificially inflating their reputation scores. Unlike Proof-of-Stake systems, there is no economic barrier (no minimum stake) to creating a validator identity.

**Mitigation Roadmap**:
- Minimum stake requirement via `PporTreasury.sol` — validators must lock tokens to participate.
- IP subnet limiting: cap the number of validators from a single `/24` subnet.
- Quadratic voting or reputation decay based on validator age (new validators start with lower weight).

---

## 5. Scalability & Performance Limitations

### 5.1 Python Single-Process Bottleneck (Search Node)

**Core Problem**: FastAPI with `ThreadPoolExecutor` is fundamentally limited by Python's GIL (Global Interpreter Lock). Even with `os.cpu_count()` workers, Python cannot effectively utilize more than 1 CPU core for CPU-bound embedding inference. Current throughput is capped at approximately 50 queries per second per node.

**Mitigation Roadmap**: 📎 **Solution planned** — GPU Inference Service (Phase 3 of Search Roadmap). A separate GPU container (NVIDIA Triton or custom FastAPI GPU service on port 8081) decouples inference from the search event loop. The `vector_service.py` delegates `encode()` calls to the GPU service via HTTP/gRPC, with CPU fallback. Expected throughput: 1,000+ QPS.

### 5.2 No Multi-Region / Geo-Awareness (All Nodes)

**Core Problem**: The Kademlia DHT and round-robin shard distribution do not account for geographic node location. A file's 45 shards may be distributed across Europe, Asia, and North America, increasing download latency. There is no mechanism to prefer "nearby" peers for shard storage or retrieval.

**Mitigation Roadmap**:
- Geo-aware peer selection: prioritize peers with lowest latency in the Kademlia routing table.
- Allow operators to configure `PREFERRED_REGIONS` (e.g., `eu,us`) for shard placement.
- Latency-weighted scoring in `peer_cache.rs` (currently only tracks success/failure counts).

### 5.3 Bootstrapping Latency for New Nodes

**Core Problem**: A new node must download a state snapshot + build its Kademlia routing table. Even after Phase 1.5 optimizations, initial bootstrap can take tens of seconds to minutes. For a browser user wanting instant access, this delay is unacceptable.

**Mitigation Roadmap**:
- Light client mode: the Flutter browser uses public gateway nodes (e.g., `api.feedo.ink`) for queries and content retrieval without running a full local node.
- Progressive bootstrap: serve cached content immediately while background sync completes.
- Pre-seeded routing table for browser builds (ship with known bootstrap PeerIds).

---

## 6. Data Integrity & Consistency

### 6.1 Optimistic Writes Before Consensus (Consensus Node)

**Core Problem**: In `register_name()` and `update_cid()`, data is written to the local SQLite database **before** PBFT consensus completes (optimistic write). The HTTP handler returns `{"success": true}` immediately. If the PBFT consensus later rejects the transaction (e.g., double-spend detected by another validator, or quorum not reached), the local state is now inconsistent with the network. The user sees "success" but other nodes do not recognize the name.

**Mitigation Roadmap**:
- Implement a rollback mechanism: store pending transactions in a `pending_optimistic_writes` queue and revert on consensus failure.
- Alternatively, wait for at least `Prepare` phase completion (2f+1 votes) before returning success to the client — trades latency for consistency.
- Short-term: mark names registered via optimistic writes with `epoch: 0` and `pending: true` so downstream consumers know the registration is not yet finalized.

### 6.2 DHT Inconsistency During Network Partition

**Core Problem**: Kademlia DHT with `Quorum::One` for manifests means that during a network partition, different segments of the network can hold different versions of the same file's manifest. When the partition heals, there is no conflict resolution mechanism — stale manifests may override fresh ones, or two competing manifests coexist.

**Mitigation Roadmap**:
- Upgrade to `Quorum::Three` for manifests (Phase 3).
- Implement Last-Writer-Wins (LWW) merge strategy using the `epoch` and `finalized_at` timestamps already present in `ResolveRes`.
- Nodes should re-publish their manifests to DHT on epoch rotation, ensuring fresh data propagates.

### 6.3 Cross-Node Schema Evolution Mismatch

**Core Problem**: Manifest v1 → v2 migration is partially backward-compatible (`storage_class: Option<String>` with `serde(default)`). However, future Manifest changes (v3 in Phase 2 with chunking support) will not be parseable by old nodes. During a rolling upgrade, nodes running old software cannot read new manifests — rendering new uploads invisible to a portion of the network.

**Mitigation Roadmap**:
- Add an explicit `manifest_version: u32` field to all future Manifest structures.
- Implement multi-version readers: nodes should be able to read N-1, N, and N+1 manifest versions.
- Protocol version negotiation during Kademlia discovery — nodes announce their supported manifest versions, and uploaders choose a compatible format.

---

## 7. Privacy & Censorship Resistance

### 7.1 Metadata Leakage via Search Queries

**Core Problem**: Federated search sends the user's plaintext query (e.g., "how to treat depression" or "opposition news Ukraine") to the top-K search nodes via `POST /p2p/search`. These nodes — potentially operated by malicious actors or under government surveillance — can log who searches for what. There is no query encryption or anonymity layer.

**Mitigation Roadmap**:
- Short-term: warn users in the browser UI that federated queries are not private. Offer a "local-only search" toggle.
- Long-term: explore private information retrieval (PIR) techniques, or route queries through an onion-routing layer (Tor/I2P integration).
- Query obfuscation: send decoy queries alongside real queries to confuse loggers (k-anonymity approach).

### 7.2 No Right to Be Forgotten (GDPR Conflict)

**Core Problem**: Content distributed via Reed-Solomon erasure coding across 45 nodes cannot be guaranteed to be fully deleted. `DELETE /delete/:hash` only deletes the local copy. GDPR Article 17 ("Right to erasure") is technically impossible in a truly decentralized storage network — once shards are distributed, there is no central authority that can enforce global deletion.

**Mitigation Roadmap**:
- Legal defense: "technically impossible" is a recognized defense under GDPR for decentralized systems (recital 69, Article 17(2) — disproportionate effort exemption).
- Tombstone mechanism: mark content as "deleted" via a consensus-backed tombstone record. Nodes respect tombstones and refuse to serve the content, even if shards still exist.
- TTL-based auto-expiration: most user-generated content (SocialPost) auto-deletes after 30 days, reducing the window of GDPR exposure.

### 7.3 Public Peer IDs = Linkable Identity

**Core Problem**: A node operator's `PeerId` (Ed25519 public key) is visible to all peers in the Kademlia DHT and gossipsub messages. If the same operator runs multiple services (storage, consensus, search), their PeerId (or IP address in search-node's case) links these roles together. This creates metadata leakage about the operator's infrastructure.

**Mitigation Roadmap**: ✅ **Partially solved** — `docker-compose.yml` already supports separate keys for different services (`STORAGE_PRIVATE_KEY` vs `NODE_PRIVATE_KEY`). Encourage operators to use unique keys per service. For search-node, deploy behind a reverse proxy with its own domain to avoid IP correlation.

---

## 8. User Experience & Adoption Barriers

### 8.1 Browser Dependency on Local Backend

**Core Problem**: The Flutter browser requires a locally running Rust engine (`browser/rust_engine`) for all P2P operations. A user cannot simply open a website — they must install a native desktop application. This is a massive adoption barrier compared to centralized alternatives (just type a URL in Chrome).

**Mitigation Roadmap**:
- Web-based version using WebAssembly (compile Rust engine to WASM via `wasm-pack`), enabling a fully in-browser experience.
- Progressive Web App (PWA) with service workers caching content locally.
- Gateway mode: lightweight browser that connects to community-run gateway nodes (e.g., `api.feedo.ink`) instead of running a full local node.

### 8.2 Trust Assumption for Non-Desktop Users

**Core Problem**: Feedo's full P2P node (Docker containers, libp2p QUIC, local Sled/SQLite/LanceDB storage) is designed for desktop/server environments. Users on mobile devices or low-power machines cannot run a full node and must rely on public gateway nodes (e.g., `api.feedo.ink`) for browsing. This introduces a trust assumption: the gateway operator could serve modified, censored, or outdated content, and the client has no way to independently verify data integrity without running a full node.

**Mitigation Roadmap**:
- Light client verification: the browser can verify content hashes (SHA256) against the consensus-node's DHT records without downloading all shards — a lightweight proof that the gateway served the correct content.
- Gateway diversity: the browser connects to multiple independent gateways and cross-checks responses (discrepancies trigger a warning).
- Mobile app as a "light client": basic browsing works via gateways with hash verification; advanced features (publishing) require a desktop node or a cloud-hosted personal node.

### 8.3 First-Visit Latency vs Centralized CDN

**Core Problem**: A centralized website served via Cloudflare/AWS CDN loads in 200-500ms from the nearest edge node. A Feedo website on first visit requires: DHT lookup for manifest → download 30+ shards from potentially distant peers → Reed-Solomon decode → render HTML. This first-visit latency can take seconds. For **repeat visits**, gateway-side caching mitigates this, but the first impression for a new user is critical — they may perceive Feedo as "slow" and abandon it before the caching benefits kick in.

**Mitigation Roadmap**:
- Gateway-side hot cache: frequently accessed content is pre-assembled and cached as full files on gateway nodes, bypassing erasure coding for popular sites.
- Pre-fetching: when a user hovers over a link, the browser starts downloading the manifest in the background.
- Progressive rendering: the browser can render HTML as soon as the first few shards arrive (streaming decode).
- Adaptive Reed-Solomon parameters for smaller files (Phase 2) — a 100 KB site should use fewer shards for faster assembly.

---

## 9. Ecosystem & Competitive Risks

### 9.1 IPFS/Filecoin Network Effects

**Core Problem**: IPFS already has a massive ecosystem (Pinata, Fleek, Web3.Storage, Brave integration). Filecoin provides the incentive layer. Feedo competes for the same market — decentralized storage and website hosting. Developers must choose: why invest time in Feedo when IPFS has more tooling, more nodes, and more users?

**Mitigation Roadmap**:
- Differentiation: Feedo is not just storage — it's an integrated browser + search + naming system. IPFS is a protocol; Feedo is a product.
- Feedo's semantic search (vector-based, multi-modal) has no equivalent in the IPFS ecosystem.
- Simpler developer experience: Feedo names (`mysite.feedo`) are human-readable by default. IPFS requires separate IPNS setup.
- Gateway compatibility: Feedo storage nodes can expose IPFS-compatible endpoints for interoperability.

### 9.2 Key Management UX Nightmare

**Core Problem**: A Feedo user/operator must manage multiple cryptographic keys:
- Ed25519 key for P2P identity (`NODE_PRIVATE_KEY` / `peer_key.bin`)
- Ethereum key for committee identity (`NODE_WALLET_ADDRESS`, `NODE_WALLET_PRIVATE_KEY`)
- Optional: Pinata API keys, Alby bearer token, Ingest API key, RSS node secret
- Storage node: separate `STORAGE_PRIVATE_KEY`

All stored in a plaintext `.env` file. For a non-technical user, this is overwhelming and insecure. Misconfiguration leads to "node not connecting" errors with cryptic log messages.

**Mitigation Roadmap**:
- Integrated wallet in the Flutter browser: generate and manage all keys from a single interface (like MetaMask but for Feedo).
- Automatic key generation: on first launch, the browser generates all required keys, stores them encrypted locally, and registers the DID + wallet in one flow.
- `NODE_WALLET_PRIVATE_KEY` should be stored in OS keychain (macOS Keychain, Windows Credential Manager, Linux `libsecret`) instead of `.env`.
- Hardware security key (Ledger/Trezor) support for validator wallets (long-term).

---

## Summary Matrix

| # | Category | Problem Count | Severity | Solution Status |
|---|----------|---------------|----------|-----------------|
| 1 | Data Storage Economics | 3 | 🔴 Critical | 📎 Tokenomics plan exists |
| 2 | Data Reliability | 2 | 🔴 Critical | Phase 3 roadmap |
| 3 | Semantic Sharding | 2 | 🟡 Medium | Phase 1.5 mitigations |
| 4 | Security & Trust | 4 | 🟡 Medium | ✅ Solutions identified |
| 5 | Scalability & Performance | 3 | 🟡 Medium | 📎 GPU Inference (Phase 3) |
| 6 | Data Integrity | 3 | 🟡 Medium | Phase 3 + Quorum upgrade |
| 7 | Privacy & Censorship | 3 | 🟠 High | Partial (legal + technical) |
| 8 | UX & Adoption | 3 | 🟠 High | Long-term roadmap |
| 9 | Ecosystem & Competition | 2 | 🟡 Medium | Differentiation + UX focus |

> **Legend**: 🔴 Critical = existential risk, must solve before Mainnet. 🟠 High = major barrier to adoption. 🟡 Medium = important but not blocking. 📎 = Solution document exists (see reference). ✅ = Solution design complete.

---

> **When writing grant applications**: Present these points transparently. Demonstrating awareness of challenges with concrete mitigation plans shows engineering maturity, deep understanding of distributed systems, and a clear product vision — all positive signals to grant reviewers.