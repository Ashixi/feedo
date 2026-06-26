# Feedo Protocol 🚀

**Feedo is the Unified Semantic Layer for the decentralized internet (let's boldly call it Web4).**

The core vision is for Feedo to serve as a foundational protocol and infrastructure layer where developers can build the decentralized applications (dApps) of the future. It provides a censorship-resistant, sharded P2P storage system with native AI-powered semantic search.

By combining global decentralized networks with an advanced AI vector engine, Feedo breaks the "filter bubble" and delivers highly relevant, algorithmically curated feeds without central authorities controlling the narrative.

---

## 🏗️ Core Architecture Overview

The Feedo ecosystem consists of three main pillars working in harmony:

1. **The Ingesters (e.g., Nostr Bridge)**
   Python-based microservices that act as the "eyes" of the network. They connect to external decentralized networks (like Nostr), scrape content in real-time, filter out noise, and forward the clean data to the main backend.

2. **The Backend (Main Node & VectorBrain)**
   A high-performance FastAPI server that acts as the brain of the operation. 
   - It receives raw data from Ingesters.
   - Uses SentenceTransformers (CLIP for images, Multilingual-e5 for text) to convert the semantic meaning of the content into dense vector embeddings.
   - Stores these vectors in **LanceDB** and exposes an algorithmic feed endpoint (/api/v1/feed) that serves personalized content based on a user's interest vector.

3. **The P2P Node (Rust)**
   A robust, libp2p Kademlia DHT-based Rust node. This allows independent Feedo instances to connect globally, sharding the workload and sharing semantic clusters (global knowledge map) without relying on a centralized database.

---

## 🛡️ The "Stateless Indexer" Concept (Nostr Integration)

A key architectural and legal pillar of Feedo is the **Stateless Indexer** model, applied specifically to our Nostr integration. 

When the Nostr Bridge scrapes a post:
- We **process the text and images solely to extract their semantic meaning** (mathematical vectors).
- Once the vector is generated, **the original text content and images are instantly discarded**. We do not save them in our PostgreSQL or LanceDB databases.
- Feedo only stores the hash_id, the generated ector, and a elay_url pointer.

This means Feedo is not a hosting provider. It simply tells frontend clients *where* to find the content (the Nostr Relay) and *how relevant* it is to the user (the vector). The client's device fetches the actual text and images directly from the decentralized source.

---

## 💻 Quickstart Guide (Local Development)

You can spin up the entire Feedo Protocol locally in just a few steps using Docker.

### Prerequisites
- Docker and Docker Compose
- Git

### Step 1: Clone the repository
```bash
git clone https://github.com/Ashixi/feedo.git
cd feedo
```

### Step 2: Configure Environment
Copy the provided example environment file:
```bash
cp .env.example .env
```
Open `.env` and configure your credentials (e.g., set `INGEST_API_KEY` and `POSTGRES_PASSWORD`).

### Step 3: Run the Protocol
The project uses two separate Docker Compose files:

**Start the Main Stack** (PostgreSQL, FastAPI Backend, Rust P2P Node):
```bash
docker-compose build
docker-compose up -d
```

**Start the Nostr Bridge** (The data scraper worker):
```bash
docker-compose -f docker-compose.nostr.yml up -d
```

### Validation
To verify the system is running:
- Open your browser and navigate to `http://localhost:8040/docs` to see the FastAPI Swagger UI.
- Check the docker logs to ensure the containers are healthy:
  ```bash
  docker-compose logs -f feedo-backend
  docker-compose -f docker-compose.nostr.yml logs -f feedo-nostr-bridge
  ```

---

## 📂 Repository Structure

- /protocol/backend - The FastAPI Main Node, VectorBrain logic, and PostgreSQL models.
- /protocol/p2p-node - The Rust libp2p node handling global DHT communication.
- /protocol/ingesters - Specialized workers (e.g., 
ostr-bridge) that fetch data.
- /feedo_search_ui - The cross-platform Flutter frontend application for interacting with the protocol.
