# Feedo Protocol Architecture

This directory (/protocol) contains the core microservices that power the Feedo network. The system is designed to be highly modular, scalable, and decentralized.

## Architecture Breakdown

The protocol consists of three primary components:

1. **Backend API (/backend)**
   The central FastAPI server. It provides REST endpoints for the frontend (like /api/v1/feed), manages the PostgreSQL metadata database, and runs the **VectorBrain** (LanceDB + AI embeddings) to analyze and curate content.

2. **P2P Node (/p2p-node)**
   A Rust-based background service using libp2p. It connects to a global Kademlia DHT, allowing independent Feedo instances to discover each other, share vector centroids (global knowledge map), and prevent centralization. It communicates with the Python backend via local HTTP/gRPC.

3. **Ingesters (/ingesters)**
   Stateless worker scripts that connect to external data sources. The primary ingester is the **Nostr Bridge** (/ingesters/nostr-bridge), which listens to decentralized Nostr relays, filters out low-quality posts (like simple replies), and pushes high-quality content to the Backend's Ingest API.

## Data Flow (Stateless Indexer)

Feedo operates as a **Stateless Indexer**, meaning it does NOT host user-generated content.

1. **Scraping**: The Ingester pulls a raw post from Nostr.
2. **Filtering**: The Ingester immediately drops replies and short/gibberish posts to save bandwidth.
3. **Ingestion**: The remaining posts are sent via HTTP POST to the Backend (/api/v1/ingest/post).
4. **Vectorization**: The Backend uses SentenceTransformers (and CLIP for images) to convert the post's text/image into a dense mathematical vector (e.g., 384 dimensions).
5. **Discarding**: The Backend **deletes the original text and images**. It only saves the vector, the author's public key, and a elay_url pointing to where the original post lives.
6. **Serving**: When a user opens the app, the Backend calculates which vectors match their interests (Anti-Bubble algorithm) and returns the hash_id and elay_url.
7. **Client Rendering**: The user's device fetches the actual text and images directly from the decentralized relay.
