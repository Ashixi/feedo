# Feedo Ecosystem: Global Product Roadmap

This document outlines the high-level strategic roadmap for the Feedo ecosystem. Unlike the technical roadmaps for individual nodes, this document focuses on **product, users, economics, and adoption**.

---

## Phase 0: "Genesis" (Current State)
*We are here. The foundation is laid.*

**Focus:** Proof of Concept (PoC) and Architecture Validation.
- **Technology:** Core logic for all three microservices implemented (Storage with Reed-Solomon, Consensus with PBFT & Cryptographic Sortition, Search with Semantic Sharding).
- **Product:** Hybrid browser MVP (Web2 + Web3) capable of searching and rendering decentralized content.
- **Security:** Audited conceptual risks (e.g., restricted flat namespace to `.feedo` to prevent early cybersquatting).
- **Status:** Ready for microgrant pitches.

---

## Phase 1: "Developer Adoption & Stability" (Months 1-3)
*Grant funding. Focus on early developers.*

**Goal:** Onboard the first 100 developers and host the first 50 real websites/dApps on the network.
- **Go-to-Market:** Partner with student hackathons. Pitch Feedo as a free sandbox for hosting demo projects.
- **Product (DX - Developer Experience):**
  - Release **Feedo SDK** (JavaScript/TypeScript and Dart) for easy network integration from any frontend.
  - Release CLI tool (`feedo-cli`) for one-click static site deployments (HTML/CSS/JS).
- **Technology (Core Stabilization):**
  - Fix critical tech debt: implement Rollback mechanics for optimistic writes (Consensus).
  - Implement basic Garbage Collection (`ttl_days`) to clear temporary Storage.
- **Team:** Attract first volunteer contributors (juniors) to expand the browser UI.

---

## Phase 2: "Incentivized Testnet" (Months 4-6)
*Focus on node operators and network scaling.*

**Goal:** Expand the network from a solo-operation to 50-100 independent node operators.
- **Go-to-Market:** Launch a gamified testnet. Implement leaderboards tracking node uptime and processed requests. Promise future rewards (premium domains, starting balances) for top participants to solve the "free-rider" node problem.
- **Product:**
  - Radically simplify node deployment (One-click Docker Compose).
  - Launch a public Gateway (e.g., `api.feedo.ink`) so users can open `.feedo` links without running a local node.
- **Technology (Performance & Reliability):**
  - **GPU Inference Service** for Search Node to break Python GIL bottlenecks.
  - Upgrade to `Quorum::Three` for manifests and implement Proactive Healing to protect against data loss during node churn.
- **Governance:** Introduce the FIP (Feedo Improvement Proposals) framework for community-driven changes.

---

## Phase 3: "Economy & Tokenomics" (Months 7-12)
*Focus on self-sustainability.*

**Goal:** Launch financial incentives to make the network economically self-sustaining without grants.
- **Tokenomics (USDT-backed):** Launch the `PporTreasury.sol` smart contract on Polygon. Internal system credits are strictly pegged to USDT to prevent volatility.
- **Monetization:**
  - **Pay-per-byte:** Paid storage for heavy files (B2B Storage API).
  - **Vector API:** Paid access to vector search for third-party dApps (e.g., $1 per 10k queries).
  - **Premium Domains:** Smart contracts for transparent auctions of premium/short `.feedo` domains.
  - **Contextual Ads:** Launch privacy-preserving vector-based advertising in the browser search results.
- **Technology:** Implement Spillover mechanics for semantic shards to resolve cluster imbalance during homogenous data floods.

---

## Phase 4: "The Alternative Internet" (Mainnet)
*Focus on mass market and full decentralization.*

**Goal:** Break out of the crypto-niche and scale to 2000+ nodes.
- **Product:**
  - Browser compiled to WebAssembly (WASM) — users can access Feedo directly from Chrome/Safari without installing anything.
  - Ecosystem expansion: a marketplace of dApps built exclusively on Feedo's CRDT and Storage layers.
- **Security & Moderation:** Implement consensus-based AI moderation or decentralized staking arbitration to handle illegal content at the protocol level (Phase 3 from `KNOWN_CHALLENGES.md`).
- **Scale:** The network operates fully autonomously. The founder transitions to being just one of many core open-source contributors.
