# FEEDO: The Alternative Internet Layer

- **Team Name:** FEEDO (Solo Founder)
- **Payment Details:**
  - **DOT**: 16XDwXnayh7twFteHXF4ruCczQymJ8buXCwo7uFw7JVXMuCP
  - **Payment**: 16XDwXnayh7twFteHXF4ruCczQymJ8buXCwo7uFw7JVXMuCP (USDT) 
- **Level:** 1

## Project Overview :page_facing_up:

### Overview

- **Tagline:** FEEDO is an Alternative Internet Layer powered by the world’s first Decentralized AI Search Engine.
- **Description:** Most Web3 projects today are impossible to find without centralized search engines. FEEDO solves this by providing a full-stack ecosystem: a Kademlia-based CRDT storage layer (using Reed-Solomon), a censorship-resistant naming system (`.feedo` via PBFT), and a semantic vector search engine. All of this is natively accessible through a unified hybrid browser that seamlessly bridges Web2 and Web3. We are not just building a search engine; we are building a Web3 internet and immediately providing the tool to search it.
- **Integration with Substrate / Polkadot:** The FEEDO SDK and CLI developed in this grant will allow Substrate and Polkadot developers to natively integrate their dApps into this Alternative Internet Layer. Polkadot developers will be able to publish their frontend applications directly to the FEEDO network and leverage decentralized AI semantic search out-of-the-box.
- **Interest in creating this project:** A critical problem in Substrate, Polkadot, and the Web3 ecosystem as a whole is that while backend logic is highly decentralized (via smart contracts), the frontend layer and search functionalities are still heavily reliant on centralized Web2 servers. FEEDO aims to bridge this gap by providing a sovereign infrastructure layer.

### Project Details

- **Technology Stack:**
  - Backend: Rust, Python, FastAPI, LanceDB (Vector DB)
  - P2P/Network: Kademlia DHT, PBFT Consensus, Reed-Solomon Erasure Coding, CRDT (LWW-Map/AW-OR-Set)
  - SDK/Tooling (Proposed): TypeScript, Python, Rust
- **Documentation:**
  - Architecture and operational docs are already established in our repository for each node type (Storage, Consensus, Search).
- **What your project is *not*:** FEEDO is not an Ethereum L2, a smart contract platform, or a generic hosting provider. It is a sovereign L1 P2P network optimized specifically for providing an alternative web experience with built-in semantic search.

### Ecosystem Fit

- **Where and how does your project fit into the ecosystem?** FEEDO fits at the fundamental infrastructure layer, providing a full-stack Alternative Internet for dApps built on any chain, including Polkadot.
- **Target audience:** Parachain developers, dApp developers, and Web3 end-users using the FEEDO Hybrid Browser.
- **What need does your project meet?** It removes the reliance on centralized web infrastructure for Web3 projects, offering a fully decentralized stack (naming + storage + AI search) that developers can interact with programmatically via our SDKs.
- **Are there any other projects similar to yours?** While projects like IPFS offer decentralized file storage, they lack a native, fast semantic search layer and a built-in naming system without external dependencies (like ENS). FEEDO integrates the data layer, naming, and vector search natively, creating a cohesive Alternative Internet.

## Team :busts_in_silhouette:

### Team members

- Name of team leader: Andrii Shumko

### Contact

- **Contact Name:** Andrii Shumko
- **Contact Email:** andriishumko@gmail.com
- **Website:** https://github.com/Ashixi/feedo

### Legal Structure

- **Registered Address:** N/A (Individual Developer)
- **Registered Legal Entity:** N/A

### Team's experience

**Andrii Shumko:**
Andrii is a highly driven software architect and full-stack engineer with a deep passion for decentralized systems and artificial intelligence. Operating as a solo founder, he has independently architected and developed the entire FEEDO L1 infrastructure from scratch.

With extensive expertise in systems programming (Rust) and AI integration (Python), Andrii specializes in building large-scale distributed data systems. His work on FEEDO demonstrates a profound understanding of complex P2P networking protocols (Kademlia DHT), custom consensus mechanisms (PBFT), and data availability solutions (Reed-Solomon erasure coding, CRDTs). Beyond the backend, Andrii is also proficient in cross-platform frontend development (Dart/Flutter), allowing him to build unified user experiences like the FEEDO Hybrid Browser.

Driven by the vision of a truly decentralized internet where both backend logic and frontend assets are free from centralized cloud providers, Andrii is dedicated to bridging the gap between Web3 infrastructure and AI capabilities. He is highly capable of executing complex technical roadmaps independently and is committed to delivering robust, open-source tools for the broader Web3 developer ecosystems.

### Team Code Repos

- https://github.com/Ashixi/feedo

Team member GitHub accounts:
- https://github.com/Ashixi

## Development Status :open_book:

FEEDO is currently in a functional MVP state (Phase 0).
- Core node logic (Consensus, Storage, Search) is fully implemented.
- Comprehensive technical challenges and roadmap planning have been documented (see `KNOWN_TECHNICAL_CHALLENGES.md` and `GLOBAL_ROADMAP.md` in the repository).

## Development Roadmap :nut_and_bolt:

### Overview

- **Total Estimated Duration:** 2 months
- **Full-Time Equivalent (FTE):** 1
- **Total Costs:** 5,000 USD
- **DOT %:** 50%

### Milestone 1 — FEEDO Client SDKs (Application Tooling)

- **Estimated duration:** 1 month
- **FTE:** 1
- **Costs:** 2,500 USD

| Number | Deliverable | Specification |
| -----: | ----------- | ------------- |
| **0a.** | License | Apache 2.0 / MIT |
| **0b.** | Documentation | We will provide inline documentation and a tutorial explaining how a Web3 developer can integrate FEEDO search and the Alternative Internet Layer into a React/Substrate dApp. |
| **0c.** | Testing and Testing Guide | Core functions of the SDKs will be covered by unit tests. |
| **0d.** | Docker | We will provide Dockerfiles to spin up a local FEEDO testnet for SDK interaction. |
| 1. | TypeScript SDK | We will deliver a TS/JS library allowing developers to query the FEEDO Search Node and publish content without running a local node. |
| 2. | Python SDK | We will deliver a Python library allowing AI and backend developers to easily ingest datasets into the FEEDO network. |
| 3. | Rust SDK | We will deliver a Rust crate containing the core P2P client logic for native integrations. |

### Milestone 2 — Protocol Security Upgrades & FEEDO CLI

- **Estimated Duration:** 1 month
- **FTE:** 1
- **Costs:** 2,500 USD

| Number | Deliverable | Specification |
| -----: | ----------- | ------------- |
| **0a.** | License | Apache 2.0 / MIT |
| **0b.** | Documentation | We will provide a tutorial demonstrating the full lifecycle of deploying a decentralized application to FEEDO using the new CLI. |
| **0c.** | Testing and Testing Guide | Unit and integration tests for the CLI and protocol upgrades. |
| **0d.** | Docker | Updated Docker-compose stack testing the new AuthZ protocol rules. |
| 1. | Protocol AuthZ | We will implement cryptographic signature verification (Ed25519/Secp256k1) in the Consensus and Storage nodes to prevent unauthorized overwrites of `.feedo` domains. |
| 2. | Protocol Versioning | We will implement manifest history for `.feedo` domains, allowing seamless version rollbacks. |
| 3. | FEEDO CLI | We will deliver a Developer CLI tool supporting automated deployment (`feedo deploy`), domain management (`feedo domain register`), and deployment rollbacks (`feedo rollback`). |

## Future Plans

- Phase 2 focuses on an Incentivized Testnet with node operator telemetry and leaderboards.
- Phase 3 focuses on migrating our treasury logic to the Polkadot ecosystem. We plan to build the FEEDO economic layer using `ink!` smart contracts on a Substrate parachain and leverage Polkadot Asset Hub for USDT transactions, driving direct utility and transactions to the Polkadot ecosystem.
- Long-term plans include transitioning the Search Node to a fully decentralized GPU inference network to support 2B+ parameter asymmetric semantic search models.
