const String aboutProjectMarkdown = '''
# About Feedo Protocol

Feedo Protocol is a decentralized infrastructure base layer (Data Layer) designed to organize, deduplicate, and semantically structure information streams across the open internet in real time.

## Vision

The modern internet has mastered the infinite generation and copying of information (reposts, SEO spam, information noise) but lacks the ability to efficiently structure its underlying meaning. Feedo Protocol solves this fundamental problem by transforming chaotic data streams into an ordered, cryptographically verified knowledge graph.

It is a decentralized semantic layer upon which next-generation social applications, decentralized search engines, and AI-oriented solutions can be built.

## Technical Architecture

The Feedo system consists of several key innovative layers:

### 1. Distributed Storage (Data Layer)
Data is not owned by a single corporation nor stored on centralized servers. All information is distributed among P2P network participants using modern technologies: Rust, libp2p, Kademlia DHT, and erasure coding. This ensures that content remains censorship-resistant and the network has no single point of failure.

### 2. Semantic AI Layer (Vector Brain)
Every published data payload is automatically vectorized (transformed into a vector embedding using LLM models) and added to a distributed semantic database. The protocol continuously compares new data with existing entries to find semantic duplicates and group related events.

### 3. Automated Information Deduplication
If dozens of different channels or users publish the exact same information, Feedo does not present dozens of copies. Instead, the system creates a semantic cluster. In this way, information ceases to be a stream of spam and becomes part of a unified knowledge graph.

### 4. Anti-bubble Mechanisms
Content delivery is not optimized for maximum engagement or ragebait. A specialized anti-bubble algorithm balances relevance with discovery, ensuring semantic diversity and presenting alternative perspectives natively at the protocol level.

### 5. Provenance and Integrity
The entire ecosystem is built on a zero-trust principle. Every data entry is cryptographically signed by the author's key, receives a unique hash, and is linked to previous records (Content Chain). This allows reliable tracking of the information source, analysis of its propagation, and makes silent retroactive alteration of history impossible.

## DePIN Infrastructure

To support a large-scale decentralized network, the protocol utilizes a two-tier physical infrastructure network (DePIN):
1. Storage Nodes: Lightweight nodes that guarantee Data Availability and handle replication across the P2P network.
2. Compute Nodes: GPU-accelerated nodes that perform heavy computational tasks for text vectorization and semantic indexing.

## Ecosystem Future

Driven by a Protocol-First paradigm, Feedo operates as a White-label solution. Any developer can spin up their own node and create a custom client, application, or platform. All these discrete applications instantly become part of a single global data layer, enriching the shared index and tearing down isolated platform silos.

Feedo Protocol is the internet that understands the meaning of information.
''';
