# Feedo P2P Node (Rust)

This directory contains the Rust microservice that handles all peer-to-peer (P2P) networking for the Feedo Protocol.

## Purpose

The Backend API is great at analyzing data (VectorBrain), but it relies on this Rust node to talk to the rest of the world. By using libp2p, this node connects to a global Kademlia Distributed Hash Table (DHT). 

This allows multiple Feedo instances (Supernodes) to:
- Discover each other.
- Share and synchronize global semantic centroids (the "Global Knowledge Map").
- Operate without a central, centralized server.

## Technologies

- **Rust**: For memory safety and extreme networking performance.
- **libp2p**: The industry-standard modular P2P networking stack (used by IPFS, Polkadot, Ethereum).
- **Prost / Tonic (gRPC)**: For high-speed internal communication between this Rust node and the Python FastAPI Backend.

## Building and Running

### 1. Requirements
- Rust toolchain (cargo, ustc)
- protobuf-compiler (Required for building the .proto files in uild.rs).

### 2. Compilation
The uild.rs script will automatically compile the protobuf definitions located in /proto.
\\\ash
cargo build --release
\\\

### 3. Running
\\\ash
cargo run --release
\\\

By default, the node will listen on UDP port 4001 for P2P traffic, and expose an internal HTTP interface on 8050 for the Python backend.
