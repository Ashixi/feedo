# Feedo Network: Complete Architecture Guide & Documentation

Welcome to the official documentation for the **Feedo** protocol — the first decentralized search network for the Nostr ecosystem, powered by a Kademlia DHT and Lightning Network micropayments.

This document covers the entire network architecture, node operator instructions, and integration guides for Nostr client developers.

---

## Table of Contents
1. [Global Network Architecture](#1-global-network-architecture)
2. [Tokenomics & Lightning Network](#2-tokenomics--lightning-network)
3. [How to Run a Feedo Node](#3-how-to-run-a-feedo-node)
4. [Proxy (Variant B): Bridge for Existing Clients](#4-proxy-variant-b-bridge-for-existing-clients)
5. [Direct Integration (Variant A) & The Spider](#5-direct-integration-variant-a--the-spider)
6. [For Nostr Client Developers](#6-for-nostr-client-developers)

---

## 1. Global Network Architecture

The Feedo network consists of autonomous nodes communicating via a P2P protocol (based on `libp2p` Kademlia and GossipSub).
Each node consists of two components working in tandem:
1. **Rust Core (`feedo-core`):** Responsible for pure P2P communication. Stores text embeddings in a decentralized hash table (DHT), discovers peers, and processes GossipSub messages.
2. **Python API (`feedo-api`):** Responsible for business logic. Performs semantic search (vector comparison), generates Lightning invoices, verifies cryptographic signatures, and serves HTTP/WebSocket requests.

**Types of Nodes in the Network:**
- **Treasury Node (Main Bank):** A special node (usually the core developer's node) that manages the "ledger" for users (credit balances) and accepts real satoshis from the Lightning Network.
- **Compute Node (Worker Node):** A regular node. It does not handle direct fiat/crypto intake. When it processes a search request, it delegates the financial verification to the Treasury Node.

---

## 2. Tokenomics & Lightning Network

Because routing fees in the Lightning Network make micropayments of 2 satoshis per search unprofitable, Feedo uses a **Virtual Treasury (Layer 3 Ledger)** architecture.

### Payment Lifecycle:
1. A user visits the web interface of a Treasury Node and generates an invoice to Top Up their balance.
2. The user pays the invoice (e.g., 1000 satoshis) via Alby, Wallet of Satoshi, etc.
3. The Treasury Node credits this amount to the virtual balance of the user's Nostr pubkey.
4. The user begins searching. Every search query deducts **2 credits (satoshis)**.
5. Profit distribution per search:
   - **1.9 satoshis (95%)** go to the Compute Node that physically executed the search.
   - **0.1 satoshis (5%)** go to the developer's wallet (Protocol Tax).

Compute nodes can withdraw their earned satoshis at any time by simply pasting their Lightning Invoice on the Treasury Node's Withdraw page and signing the request with their Nostr key.

---

## 3. How to Run a Feedo Node

### Requirements
Any server (VPS) with Docker support and a static IP address (preferably with a domain name and HTTPS, although not mandatory).

### Instructions (No git clone required):
You do not need to download the entire source code. Everything runs via pre-built Docker images!

1. Create a new folder on your server:
   ```bash
   mkdir feedo-node && cd feedo-node
   ```
2. Create a `docker-compose.yml` file and paste the following content:
   ```yaml
   services:
     db:
       image: postgres:15-alpine
       restart: always
       env_file:
         - .env
       environment:
         - POSTGRES_USER=${POSTGRES_USER:-feedo_user}
         - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-secure_db_password_123}
         - POSTGRES_DB=${POSTGRES_DB:-feedo_db}
       volumes:
         - postgres_data:/var/lib/postgresql/data
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U feedo_user -d feedo_db"]
         interval: 5s
         retries: 5
   
     feedo_node:
       image: feedo-network/feedo-node:latest
       restart: always
       ports:
         - "8000:8040"
         - "4001:4001/udp"
       env_file:
         - .env
       environment:
         - POSTGRES_USER=${POSTGRES_USER:-feedo_user}
         - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-secure_db_password_123}
         - POSTGRES_DB=${POSTGRES_DB:-feedo_db}
         - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER:-feedo_user}:${POSTGRES_PASSWORD:-secure_db_password_123}@db:5432/${POSTGRES_DB:-feedo_db}
         - RUST_CORE_URL=http://127.0.0.1:8041/local/publish
         - PYTHON_API_URL=http://127.0.0.1:8040
         - NODE_WALLET_PRIVATE_KEY=${NODE_WALLET_PRIVATE_KEY}
         - NODE_WALLET_ADDRESS=${NODE_WALLET_ADDRESS:-feedo_local_node}
         - PUBLIC_API_URL=${PUBLIC_API_URL:-""}
         - TREASURY_URL=${TREASURY_URL:-""}
         - TREASURY_API_KEY=${TREASURY_API_KEY:-""}
         - BOOTSTRAP_NODES=${BOOTSTRAP_NODES:-""}
         - ALBY_BEARER_TOKEN=${ALBY_BEARER_TOKEN:-""}
       depends_on:
         db:
           condition: service_healthy
       volumes:
         - rust_db_data:/app/db
   
   volumes:
     postgres_data:
     rust_db_data:
   ```

3. Create a `.env` file and configure the key parameters:
   ```env
   # Your node's private key (in Hex). You can generate one with any Nostr tool.
   NODE_WALLET_PRIVATE_KEY=your_private_key
   
   # Your node's public key. This is where your earned 1.9 satoshis per search will be credited.
   NODE_WALLET_ADDRESS=your_public_key
   
   # (MANDATORY for Compute nodes) — URL of the Main Bank.
   # If left empty, your node becomes a bank itself (managing local balances).
   # However, to receive search traffic from the official Spider, you MUST use the official bank.
   TREASURY_URL=https://api.feedo.ink
   
   # Your public domain or IP. If specified, your node will advertise itself in the P2P network.
   PUBLIC_API_URL=https://mynode.com
   ```

4. Run the node in the background:
   ```bash
   docker-compose up -d
   ```

If you leave `PUBLIC_API_URL` empty, your node will still operate in the P2P network and can earn satoshis as a backend for the **Proxy**.

---

## 4. Proxy (Variant B): Bridge for Existing Clients

Many existing Nostr clients (Amethyst, Primal, Coracle) already support search via standard Nostr relays (according to the **NIP-50** protocol).
However, they expect a WebSocket connection (`wss://`) and send search queries formatted as a standard Nostr `REQ`.

To prevent client developers from writing new code, we built the **Feedo Proxy** (`proxy.py`).

**How it works:**
- The Proxy is a lightweight standalone service that "pretends" to be a standard Nostr relay.
- Clients connect to it: `wss://proxy.feedo.space`.
- When a user types a search query in Amethyst, the Proxy intercepts the request, queries the Kademlia DHT (any Feedo node), performs semantic search, and returns the results to Amethyst formatted as standard Nostr `EVENT`s.
- Payment is handled either via subscription or deducted from the client's balance (depending on the proxy configuration).

**Why is it needed?** It is the perfect tool for instant mass-market adoption. It is a "Zero-Code" integration approach for lazy client developers.

---

## 5. Direct Integration (Variant A) & The Spider

For modern clients who want to use a direct API (without WebSocket hacks) and completely decentralized search, we offer **Direct Integration**.

### The Centralization Problem
If the developer of Amethyst simply hardcoded `https://api.feedo.space` into their app, it would violate the principles of decentralization. If that server goes down, search breaks for everyone.

### The Solution: Feedo Tracker (Spider) 🕷️
To solve this problem, we created a P2P gossip ecosystem:
1. **Network Discovery:** Every 60 seconds, every Feedo node shouts into the P2P network: *"Hello, my domain is https://mynode.com"*. This domain is cryptographically signed by its Nostr key (Anti-Spoofing).
2. Nodes share these domains with each other.
3. **Feedo Spider (`feedo-tracker`):** A separate standalone project. It is a crawler that traverses the P2P network, aggregates all discovered domains, and performs Health Checks on them to ensure they are alive.
4. The Spider exposes a `GET /nodes` endpoint, which returns a clean array of fast, living nodes.

---

## 6. For Nostr Client Developers

If you are developing a Nostr client, you have **two integration paths** for decentralized Feedo search.

### Path 1: The Easiest (via Proxy)
Simply add `wss://proxy.feedo.space` (or another trusted proxy) to the list of default Search Relays in your client. Your existing NIP-50 implementation will instantly start working, and the results will be incredibly accurate.

### Path 2: The Best (Direct API + Spider)
If you want full control and the speed of a REST API:
1. Run your own instance of the **Feedo Tracker (Spider)** (or use the public Foundation tracker).
2. In your app, before the first search, request your Tracker:
   ```http
   GET https://tracker.yourdomain.com/nodes
   ```
3. You will receive an array: `["https://node1.com", "https://node2.com", ...]`.
4. Randomly (or by lowest ping) select one node from this list.
5. Make a direct POST request containing your user's signed Nostr event:
   ```http
   POST https://node1.com/api/v1/client_search
   ```
   **Payload:**
   ```json
   {
       "event": {
           "id": "...",
           "pubkey": "...",
           "created_at": 1234567,
           "kind": 27235,
           "tags": [],
           "content": "Your AI search query",
           "sig": "..."
       }
   }
   ```
6. You will receive an instant JSON response containing relevant posts (formatted as standard Nostr events), and 2 satoshis will be deducted from the user's virtual balance (on the Treasury Node).

   **Example Response Payload:**
   ```json
   [
       {
           "id": "e8...4f",
           "pubkey": "npub1...",
           "created_at": 1718660000,
           "kind": 1,
           "tags": [],
           "content": "Here is a post perfectly matching your query!",
           "sig": "..."
       },
       {
           "id": "a1...9c",
           "pubkey": "npub1...",
           "created_at": 1718650000,
           "kind": 1,
           "tags": [],
           "content": "Another relevant post...",
           "sig": "..."
       }
   ]
   ```
   This array of objects is completely compatible with existing Nostr client parsers, so you can render them directly in the news feed.

---
*Documentation generated as part of the Feedo Layer 3 Ledger architecture.*
