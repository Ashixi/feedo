# Feedo Tokenomics & Economic Model — Concept Plan

> **Status**: Well-formed concept — the core architecture and pricing are defined, but specific details may evolve as the protocol matures and real-world data informs adjustments.
> **Audience**: Internal use, grant applications, ecosystem participants.

---

## Overview

This document describes the economic architecture of the Feedo network, pricing principles for services, and the fair revenue distribution formula among ecosystem participants. The model is based on fiat-pegged stablecoins (USDT) and microtransactions — **no volatile internal token** is used for payments.

---

## 1. Payment Architecture (Pay-As-You-Go)

### Treasury

All user payments flow into a single **`PporTreasury.sol`** smart contract on the **Polygon** network, denominated in **USDT**.

### Virtual Accounting

The Feedo network internally tracks the payment event via `eth_bridge` and immediately distributes the funds as "virtual balances" among the nodes that performed useful work. No on-chain transaction is needed for each micro-payment — accounting is off-chain, settlement is on-chain.

### Cash Out

A node operator accumulates a virtual balance inside the network. When they want to withdraw real money:

1. The consensus layer generates a **cryptographic proof** of the operator's accumulated balance.
2. The operator submits this proof to the `PporTreasury.sol` contract on Polygon.
3. The contract verifies the proof and releases the USDT in a **single transaction**.

This minimizes gas costs — operators batch their earnings and withdraw infrequently.

---

## 2. Global Revenue Split (5 / 5 / 90)

Every dollar entering the network from users is automatically split:

| Share | Recipient | Purpose |
|-------|-----------|---------|
| **5%** | **Foundation Fee** | Sent to the developer/founder wallet. Used for marketing, security audits, infrastructure (bootstrap nodes), and ecosystem grants. |
| **5%** | **Consensus Fee** | Distributed equally among the active validators (Top-21) who maintained the network, verified transactions, and participated in PBFT consensus during the epoch. This is the financial incentive to run powerful, secure validator servers. |
| **90%** | **Provider Fee** | Goes directly to the nodes that performed the actual physical work — Storage Nodes and Search Nodes. This creates a powerful market incentive for ordinary users to connect their computers to the Feedo network. |

---

## 3. Service Pricing (Price List)

### 3.1 Identity & Domains (Consensus Nodes)

The domain registry is the foundation of the ecosystem, generating the baseline revenue stream. Since consensus nodes maintain the domain database, **90% of the Provider Fee from all domain operations is distributed among ALL active consensus nodes** (not just the Top-21 validators).

| Service | Price | Notes |
|---------|-------|-------|
| **User DID Registration** | **Free** | Analogous to creating a Google account. Keys are generated locally in the browser — zero-friction onboarding for millions of users. |
| **Node Operator License (Anti-Sybil)** | **$1–$5 (one-time)** | If a DID holder wants to become a service provider (Storage, Search, Consensus) and earn money, they purchase this license. Protects the network from millions of fake servers attempting to steal rewards. |
| **Domain Rental** | **$5/year** | Standard annual registration for a `.feedo` domain. |
| **Perpetual Domain Ownership** | **$100 (one-time)** | The user receives a Web3 domain forever (effectively an NFT). No renewal fees. |
| **Aftermarket (Auctions)** | **5% royalty** | Users can resell premium domains to each other. The network collects a 5% royalty on every successful transaction, distributed via the standard 5/5/90 split. |

### 3.2 Decentralized Storage (Storage Nodes)

| Service | Price | Notes |
|---------|-------|-------|
| **Data Storage** | **$5 per 1 TB** | The payment (specifically 90% of it, per the revenue split) is distributed among the storage nodes that physically store the erasure-coded replicas of that data volume. |

### 3.3 Search & Vectorization (Search Nodes)

AI-powered data parsing and semantic search is a key differentiator for Feedo:

| Service | Price | Notes |
|---------|-------|-------|
| **Raw Data Parsing by DID** | **Free** | Ensures Web3 openness. DDoS protection is enforced via P2P-level rate limiting, verified through cryptographic signatures of the initiator. |
| **Vector Search (AI / Embeddings / LanceDB)** | **$1 per 10,000 queries/vectors** | The user purchases a "quota" that is gradually consumed during complex search queries. Funds go to the Search Nodes that spent CPU/GPU resources on computation. |

---

## 4. Advantages of This Model

### Understandable for Web2 Users

No complex internal currency with a volatile exchange rate. People pay in familiar dollars (USDT) at **fixed, transparent prices**. A domain costs $5/year — just like traditional registrars. Storage costs $5/TB — comparable to centralized cloud providers but with the user receiving 90% of the revenue instead of a corporation.

### High Profitability for Providers

The **90% provider share** makes "mining" on hard drives and GPUs in the Feedo network significantly more profitable than traditional corporate clouds, where the corporation takes 100% of the margin. A storage node operator keeps almost all of the revenue they generate.

### Economic Sustainability

The Foundation receives a steady income stream for ongoing development (5% of all revenue). The network does not depend on token inflation — all services are backed by **real fiat inflows** (USDT). This creates a sustainable, non-speculative economic foundation.

### Sybil Resistance Without Staking Millions

The $1–$5 node operator license is a minimal but effective barrier: it costs almost nothing for a legitimate operator, but makes it economically impractical to spawn millions of fake nodes. Combined with IP subnet limiting and reputation decay, this creates multi-layered Sybil protection.

---

## 5. Integration with the Feedo Stack

| Component | Role in Tokenomics |
|-----------|-------------------|
| **`PporTreasury.sol`** | Polygon smart contract — holds all USDT, processes cash-outs |
| **`eth_bridge.rs`** | Monitors Polygon events (`CreditClaimed`) and credits the virtual ledger |
| **`accounting.rs` Ledger** | In-memory + Sled-backed virtual balance tracking — the "bank" inside Feedo |
| **`ppor.rs` Consensus** | Generates cryptographic proofs for cash-out (validator signatures on balance snapshots) |
| **`quota.rs` StorageQuotaManager** | Enforces per-DID storage limits based on purchased quota |
| **Search Node (`vector_service.py`)** | Tracks query consumption against purchased vector quotas |

---

> **Note for grant applications**: This tokenomics model demonstrates that Feedo has a clear path to financial sustainability without relying on speculative token dynamics. The use of USDT stablecoins and fixed pricing makes the economic model predictable, auditable, and accessible to non-crypto-native users — a significant differentiator from token-inflation-based Web3 projects.