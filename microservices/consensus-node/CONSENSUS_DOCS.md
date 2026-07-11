# Consensus Node — Technical Documentation

> **Version**: 0.1.0 (Phase 1 + 1.5 complete)
> **Language**: Rust (edition 2024)
> **Last updated**: 2026-07-11

---

## 1. Overview

The **consensus-node** is a decentralised naming and ledger microservice in the Feedo ecosystem. It provides decentralised domain registration (feedo names), content addressing (CID updates), a reputation-weighted PBFT consensus protocol, and a built-in credit ledger for fee payments — all running over a libp2p P2P network without a central authority.

### Key capabilities

| Capability | Description |
|------------|-------------|
| **Name Registration** | Register `.feedo` names linked to DIDs. Consensus via PBFT with 100-credit fee. |
| **CID Update** | Update content-addressed identifiers (IPFS hashes) and gateway lists for registered names. |
| **Metadata Update** | Set `title`, `description`, and `icon_cid` for registered names. |
| **DID Management** | Create Decentralised Identifiers (`did:feedo:...`) with Ed25519/secp256k1 key verification. |
| **Credit Ledger** | Built-in accounting: 500,000 free credits per DID, 100 credits per name registration. |
| **PBFT Consensus** | Practical Byzantine Fault Tolerance with 4 phases (PrePrepare → Prepare → Commit → Finalized). |
| **Reputation System** | Validators earn/lose reputation based on voting behaviour. Top-21 by reputation form the committee. |
| **Epoch Rotation** | Every 10 minutes (configurable): committee re-election, state snapshot generation, garbage collection. |
| **State Snapshots** | Periodic Merkle-rooted state snapshots published to DHT for fast node bootstrap (Phase 1.5). |
| **Direct Messaging** | PBFT votes go direct request-response between validators instead of gossipsub flood (Phase 1). |

### High-level architecture

```
┌──────────────────────────────────────────────────────────┐
│                    External Clients                       │
│         HTTP (axum)          gRPC (tonic)                │
└──────────────┬──────────────────┬────────────────────────┘
               │                  │
┌──────────────▼──────────────────▼────────────────────────┐
│                      main.rs                              │
│  AppState { swarm_tx, name_db, did_manager, ledger }     │
│  • register_did / register_name / update_cid              │
│  • update_metadata / resolve_name_http                    │
│  • get_did_balance / resolve_cid_http                     │
│  • MyConsensusService (gRPC)                              │
└──────────────────────┬───────────────────────────────────┐
                       │ mpsc channel (SwarmCommand)
┌──────────────────────▼───────────────────────────────────┐
│                   swarm_loop.rs                           │
│  run_swarm() — single-threaded event loop                 │
│  ┌──────────────────────────────────────────────────┐    │
│  │  tokio::select! {                                 │    │
│  │    swarm events  (gossipsub / Kademlia / req-resp)│    │
│  │    command_rx    (PublishPpor / Broadcast* / ...)  │    │
│  │    epoch_tick    (rotation + snapshot + GC)       │    │
│  │  }                                                │    │
│  └──────────────────────────────────────────────────┘    │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │  ppor    │  │ name_db  │  │accounting│  │  replay  │ │
│  │   .rs    │  │   .rs    │  │   .rs    │  │   .rs    │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │
└──────────────────────────────────────────────────────────┘
```

---

## 2. Architecture

### 2.1 Protocol stack

```
┌─────────────────────────────────┐
│  HTTP REST  │  gRPC              │   ← Application layer
├─────────────────────────────────┤
│  axum (0.7) │ tonic (0.12)       │   ← Frameworks
├─────────────────────────────────┤
│  libp2p (0.53)                   │   ← P2P networking
│  ├─ Kademlia DHT (record store)  │
│  ├─ gossipsub (8 topics)         │
│  ├─ request-response (JSON)      │
│  ├─ identify + mdns (discovery)  │
│  ├─ QUIC (UDP) + TCP (fallback)  │
│  └─ noise + yamux (encryption)   │
├─────────────────────────────────┤
│  Sled (embedded KV) + SQLite     │   ← Persistent storage
├─────────────────────────────────┤
│  ethers (Polygon RPC)            │   ← On-chain committee
└─────────────────────────────────┘
```

### 2.2 Data flow: Name Registration

```
Client
  │ POST /name/register { name, did, public_key, signature }
  ▼
main.rs: register_name()
  │ 1. Verify signature (secp256k1 via did::verify_signature)
  │ 2. Check name doesn't already exist (name_db.name_exists)
  │ 3. Lookup DID locally or via DHT (LookupDidDht)
  │ 4. Check balance ≥ 100 credits (ledger.get_balance)
  │ 5. Send SwarmCommand::BroadcastNameTx
  │ 6. Write locally immediately (optimistic)
  │ 7. Publish to DHT (PublishDht)
  ▼
swarm_loop.rs: Gossipsub handler for "feedo_name_txs"
  │ 1. Verify signature again
  │ 2. Compute tx_hash
  │ 3. Store pending_name_txs entry
  │ 4. ppor_manager.mark_validated() → Prepare phase
  │ 5. Send PBFT Prepare vote to committee (direct or gossipsub)
  │ 6. Self-deliver chain → Commit → Finalized
  ▼
swarm_loop.rs: handle_finalized_tx()
  │ 1. ledger.debit(did, 100) — deduct 100 credits
  │ 2. name_db.insert_name() — persist locally
  │ 3. kademlia.put_record() — publish to DHT
  │ 4. ppor_manager.archive_finalized_state() — GC
```

### 2.3 Data flow: CID Update

```
Client
  │ POST /name/update_cid { name, cid, signature, gateways }
  ▼
main.rs: update_cid()
  │ 1. Resolve DID from name (local or DHT)
  │ 2. Lookup DID document (local or DHT)
  │ 3. Verify signature against DID's public key
  │ 4. Send SwarmCommand::BroadcastUpdateCidTx
  │ 5. Write locally immediately (optimistic)
  │ 6. Publish updated ResolveRes to DHT
  ▼
swarm_loop.rs: Gossipsub handler for "feedo_update_cid_txs"
  │ Same PBFT flow as name registration
  ▼
swarm_loop.rs: handle_finalized_tx()
  │ 1. name_db.update_cid() — persist locally
  │ 2. kademlia.put_record() — publish to DHT
  │ 3. ppor_manager.archive_finalized_state()
```

### 2.4 Module map

| File | Lines | Role |
|------|-------|------|
| `main.rs` | ~865 | Entry point: HTTP/gRPC servers, key loading, swarm init, route definitions, data structs |
| `swarm_loop.rs` | ~1330 | Core event loop: handles SwarmCommand, gossipsub, request-response, Kademlia, epoch tick |
| `ppor.rs` | ~340 | PBFT protocol: PporState, PporManager, committee selection, reputation, epoch, GC |
| `network.rs` | ~155 | Network behaviour: ConsensusBehaviour, ConsensusCodec, request-response types |
| `accounting.rs` | ~170 | Credit ledger: Ledger (HashMap + Sled), Merkle root generation, state snapshots |
| `name_db.rs` | ~215 | Name registry: SQLite schema, insert/resolve/update, metadata, full record queries |
| `did.rs` | ~180 | DID documents: DidDocument, signature verification, DidManager (Sled) |
| `replay.rs` | ~145 | State bootstrap: replay_from_snapshot (fast), replay_from_dht (legacy fallback) |
| `eth_bridge.rs` | ~140 | Polygon bridge: Web3Bridge, fetch_committee(), event listener, auto-claim daemon |

---

## 3. Module Reference

### 3.1 `main.rs` — Entry Point

**Key structures:**

```rust
// Shared application state, cloneable for Axum extractors
pub struct AppState {
    pub name_db: Arc<Mutex<NameDb>>,
    pub did_manager: Arc<Mutex<DidManager>>,
    pub swarm_tx: mpsc::UnboundedSender<SwarmCommand>,
    pub ledger: Arc<Ledger>,
}

// gRPC service implementation
pub struct MyConsensusService {
    pub ledger: Arc<Ledger>,
    pub did_manager: Arc<Mutex<DidManager>>,
    pub eth_bridge: Arc<Web3Bridge>,
    pub name_db: Arc<Mutex<NameDb>>,
    pub ppor_manager: Arc<Mutex<PporManager>>,
    pub swarm_tx: mpsc::UnboundedSender<SwarmCommand>,
}

// Transaction types
pub struct NameRegistrationTx { pub name, pub did, pub public_key, pub signature }
pub struct UpdateCidTx { pub name, pub cid, pub signature, pub gateways }
pub struct LedgerTx { pub did, pub amount, pub is_credit, pub signature }
pub struct UpdateMetadataTx { pub name, pub title, pub description, pub icon_cid, pub signature }

// Response structures
pub struct ResolveRes { pub did, pub cid, pub gateways, pub epoch, pub finalized_at, pub title, pub description, pub icon_cid, pub created_at, pub updated_at }
pub struct NameRegisterRes { pub success, pub error }
pub struct DidRegisterRes { pub did }
pub struct BalanceRes { pub balance_credits }

// Phase 1.5: State snapshot types
pub struct StateSnapshot { pub epoch, pub balances, pub names, pub merkle_root, pub created_at, pub signature, pub signer }
pub struct NameSnapshotEntry { pub name, pub did, pub cid, pub gateways, pub title, pub description, pub icon_cid, pub created_at, pub updated_at }
```

**HTTP API routes:**

| Method | Route | Handler | Description |
|--------|-------|---------|-------------|
| POST | `/did/register` | `register_did` | Generate DID from public key, credit 500,000 |
| POST | `/name/register` | `register_name` | Register `.feedo` name (100 credit fee, signature required) |
| POST | `/name/update_cid` | `update_cid` | Update CID and gateways (signature verified against DID) |
| POST | `/name/update_metadata` | `update_metadata` | Update title, description, icon_cid |
| GET | `/resolve/:name` | `resolve_name_http` | Resolve name → DID, CID, gateways, epoch, metadata |
| GET | `/resolve_cid/:cid` | `resolve_cid_http` | Reverse CID lookup → name |
| GET | `/did/:did/balance` | `get_did_balance` | Get DID credit balance |
| GET | `/did/:did/names` | `get_names_by_did` | List all names registered under a DID |

**Initialisation flow in `main()`:**

1. Open/create Sled database at `DB_DIR/sled`
2. Open/create SQLite database at `DB_DIR/names.db`
3. Start `Web3Bridge` event listener (Polygon RPC) for on-chain committee
4. Load or generate Ed25519 keypair (`NODE_PRIVATE_KEY` env or `peer_key.bin`)
5. Build libp2p swarm: QUIC + TCP, noise, yamux, gossipsub (8 topics), Kademlia (server mode), identify, mdns, request-response (`ConsensusCodec`)
6. Listen on `P2P_PORT` (UDP/QUIC)
7. Dial bootstrap nodes from `BOOTSTRAP_NODES`
8. Spawn `swarm_loop::run_swarm()` in a separate Tokio task
9. Publish local name records to DHT (for existing data on restart)
10. Start gRPC server on `GRPC_PORT` and HTTP server on `HTTP_PORT`
11. `tokio::select!` — runs until either server exits or SIGINT

### 3.2 `ppor.rs` — PBFT Consensus Protocol

**PporState** tracks one transaction through the consensus lifecycle:

```rust
pub struct PporState {
    pub view: u64,               // Current view number
    pub sequence: u64,           // Transaction sequence
    pub tx_hash: String,          // SHA256 transaction hash
    pub tx_type: i32,             // TX_TYPE_* constant
    pub phase: PbftPhase,         // Current PBFT phase
    pub prepares: HashSet<String>, // Wallet addresses that sent Prepare
    pub commits: HashSet<String>,  // Wallet addresses that sent Commit
    pub committee: HashSet<String>, // Current committee members
    pub is_validated: bool,       // Transaction data verified
    pub created_at: Instant,      // For timeout detection
}
```

**PBFT phases:**

| Phase | Description | Transition trigger |
|-------|-------------|-------------------|
| `PrePrepare` | Leader proposes transaction | `propose()` or `mark_validated()` |
| `Prepare` | Validators acknowledge they've seen the proposal | `mark_validated()` + self-deliver, then 2f+1 Prepare votes |
| `Commit` | Validators commit to the proposal | 2f+1 Prepare votes received |
| `Finalized` | Transaction is final — execute it | 2f+1 Commit votes received |

**Quorum formula:** `required_votes = (2 × committee_size / 3) + 1`. For a committee of 21, 15 votes are needed.

**PporManager fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `states` | `HashMap<String, PporState>` | Active transactions indexed by tx_hash |
| `view` | `u64` | Current consensus view |
| `node_id` | `String` | This node's wallet address |
| `secret_key` | `Option<SecretKey>` | secp256k1 key for signing PBFT messages |
| `reputation_table` | `HashMap<String, u64>` | All known validators → reputation score |
| `current_committee` | `HashSet<String>` | Current epoch's committee (≤21 validators) |
| `last_finalized_hash` | `String` | Hash of last finalized transaction (seed for next epoch) |
| `current_epoch` | `u64` | Current epoch number |
| `epoch_start` | `Instant` | When the current epoch started |
| `epoch_duration` | `Duration` | Epoch length (default 600s) |
| `finalized_archive` | `Vec<FinalizedArchiveEntry>` | GC archive of finalized transactions |
| `max_archive_size` | `usize` | Max archive entries (10,000) |

**Reputation system:**

| Event | Score change | Description |
|-------|-------------|-------------|
| Send Prepare vote | `+1` | `REP_PREPARE_VOTE` |
| Send Commit vote | `+2` | `REP_COMMIT_VOTE` |
| Invalid signature | `-5` | `REP_INVALID_SIG` |
| Timeout (no vote) | `-3` | `REP_TIMEOUT` |
| Daily inactivity | `-1` | `REP_DAILY_DECAY` (min score = 1) |

**Committee selection** (`select_committee_weighted`):
1. For each known validator: `weighted_score = hash(seed || node_id) × reputation`
2. Sort by score descending
3. Top `min(total_nodes, 21)` become the committee (minimum 1)
4. New committee is deterministic for the same seed → all nodes agree

**Epoch rotation** (`rotate_epoch`):
1. Remove timed-out transactions from `states`
2. Increment `current_epoch`
3. Reset `epoch_start`
4. Compute seed: `"{last_finalized_hash}:{current_epoch}"`
5. Re-select committee via `select_committee_weighted`

**Garbage collection** (Phase 1.5):
- `archive_finalized_state(tx_hash)`: moves finalized PporState to `finalized_archive` (keeps only tx_hash + timestamp + epoch)
- `cleanup_finalized_states(keep_epochs)`: removes archive entries older than N epochs ago
- `cleanup_timed_out()`: removes timed-out (non-finalized) states, penalizes non-voters

### 3.3 `swarm_loop.rs` — Core Event Loop

**SwarmCommand enum** — messages sent from HTTP handlers to the event loop:

| Variant | Purpose |
|---------|---------|
| `PublishPpor(PbftMessage)` | Send a PBFT vote message |
| `RelayTxToValidators { tx_type, tx_data_json, from_node, signature }` | Relay a new transaction to all committee members |
| `BroadcastNameTx(NameRegistrationTx)` | Broadcast name registration to gossipsub (legacy) |
| `BroadcastUpdateCidTx(UpdateCidTx)` | Broadcast CID update to gossipsub (legacy) |
| `BroadcastLedgerTx(LedgerTx)` | Broadcast ledger transaction to gossipsub (legacy) |
| `BroadcastUpdateMetadataTx(UpdateMetadataTx)` | Broadcast metadata update to gossipsub (legacy) |
| `PublishDidDht(String, DidDocument)` | Publish DID document to Kademlia DHT |
| `PublishDht(String, ResolveRes)` | Publish name resolution result to DHT |
| `LookupDht(String, oneshot::Sender)` | Look up a name in Kademlia DHT |
| `LookupDidDht(String, oneshot::Sender)` | Look up a DID in Kademlia DHT |
| `PublishReputationDht(String, u64)` | Publish reputation score to DHT |

**Key helper functions:**

| Function | Description |
|----------|-------------|
| `send_pbft_to_committee()` | Sends a PBFT message to all committee members via direct request-response. Falls back to gossipsub if no peer mappings are available (self-only committee). |
| `get_committee_peers()` | Returns PeerIds for current committee members (excluding self) from `wallet_to_peer` mapping. |
| `self_deliver_pbft_chain()` | Calls `handle_message()` locally up to 3 times to progress through Prepare→Commit→Finalized, sending each phase to the committee. |
| `handle_finalized_tx()` | Applies a finalized transaction to storage (name_db, ledger), publishes to DHT, and archives the PporState via GC. |

**Event loop handlers in `run_swarm()`:**

| Source | Event | Handler |
|--------|-------|---------|
| `SwarmEvent::NewListenAddr` | New P2P listen address | Log address |
| `SwarmEvent::ConnectionEstablished` | Peer connected | Log connection |
| `RequestResponse::Message::Request(TxRelay)` | New transaction from another node | Propose via PBFT, self-deliver chain |
| `RequestResponse::Message::Request(PbftVote)` | Direct PBFT vote from another validator | Process through `handle_message`, self-deliver chain |
| `Gossipsub("feedo_peer_announce")` | Peer announcement | Update `wallet_to_peer`/`peer_to_wallet` mappings, update reputation, recalculate committee |
| `Gossipsub("feedo_consensus_ppor")` | Legacy PBFT message | Process via `handle_message`, self-deliver chain (backward compat) |
| `Gossipsub("feedo_name_txs")` | Name registration tx | Verify signature → `mark_validated()` → PBFT |
| `Gossipsub("feedo_update_cid_txs")` | CID update tx | `mark_validated()` → PBFT |
| `Gossipsub("feedo_ledger_txs")` | Ledger tx | `mark_validated()` → PBFT |
| `Gossipsub("feedo_update_metadata_txs")` | Metadata update tx | `mark_validated()` → PBFT |
| `Kademlia::OutboundQueryProgressed` | DHT lookup result | Route to pending DHT query sender |
| `epoch_tick` (every 5s) | Proactive epoch check | `maybe_rotate_epoch()`, generate snapshot, publish to DHT, GC, re-publish names |

### 3.4 `network.rs` — P2P Network Behaviour

**ConsensusBehaviour** combines all libp2p behaviours:

```rust
pub struct ConsensusBehaviour {
    pub gossipsub: gossipsub::Behaviour,
    pub kademlia: kad::Behaviour<MemoryStore>,
    pub identify: identify::Behaviour,
    pub mdns: mdns::tokio::Behaviour,
    pub request_response: request_response::Behaviour<ConsensusCodec>,
}
```

**ConsensusCodec** — unified JSON codec for `ConsensusRequest`/`ConsensusResponse`:

```rust
#[serde(tag = "type")]
pub enum ConsensusRequest {
    #[serde(rename = "tx")]
    TxRelay { tx_type: String, tx_data_json: String, from_node: String, signature: String },
    #[serde(rename = "pbft")]
    PbftVote { pbft_message_b64: String, phase: i32, tx_hash: String },
}

#[serde(tag = "type")]
pub enum ConsensusResponse {
    #[serde(rename = "tx_ack")]
    TxAck { accepted: bool, reason: String },
    #[serde(rename = "pbft_ack")]
    PbftAck { received: bool },
}
```

- **Protocol**: `/feedo-consensus/1.0.0`
- **Serialisation**: JSON with `#[serde(tag = "type")]` for enum discrimination
- **PbftMessage encoding**: protobuf → base64 for transport in JSON
- `TxRequest` and `TxResponse` structs are kept for backward compatibility (deprecated)

### 3.5 `accounting.rs` — Credit Ledger

**Ledger** — in-memory HashMap backed by Sled:

```rust
pub struct Ledger {
    db: sled::Db,
    pub balances: Arc<Mutex<HashMap<String, u64>>>,
}
```

**Methods:**

| Method | Description |
|--------|-------------|
| `credit(wallet, amount)` | Add credits to wallet. Writes to Sled `balance:{wallet}`. |
| `debit(wallet, amount) → bool` | Deduct credits if sufficient balance. Returns false if insufficient. |
| `get_balance(wallet) → u64` | Read current balance from in-memory cache. |
| `generate_merkle_root() → ([u8; 32], MerkleTree)` | Build Keccak256 Merkle tree of all balances (sorted by wallet address). Uses double-hash (`keccak256(keccak256(abi.encode(address, amount)))`) for second preimage resistance. |
| `generate_state_snapshot(epoch, names, signer, secret_key) → StateSnapshot` | Generate a full state snapshot: sorted balances, Merkle root, all name entries, signed with secp256k1. |

### 3.6 `name_db.rs` — Name Registry (SQLite)

**Schema:**

```sql
CREATE TABLE name_registry (
    name TEXT PRIMARY KEY,
    did TEXT NOT NULL,
    public_key TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    cid TEXT,
    gateways TEXT,        -- JSON array of gateway URLs
    title TEXT,
    description TEXT,
    icon_cid TEXT,
    created_at INTEGER,
    updated_at INTEGER
)
```

**Key methods:**

| Method | Description |
|--------|-------------|
| `insert_name(name, did, public_key)` | Insert or replace a name record. Sets `created_at` and `timestamp`. |
| `update_cid(name, cid, gateways_json)` | Update CID and gateways for a name. |
| `update_metadata(name, title, description, icon_cid)` | Update title, description, icon_cid. Sets `updated_at`. |
| `resolve_name(name) → Option<(did, cid, gateways)>` | Basic resolve returning only core fields. |
| `resolve_name_full(name) → Option<NameRecord>` | Full resolve returning all 11 columns. |
| `resolve_cid(cid) → Option<name>` | Reverse lookup: find name by CID. |
| `name_exists(name) → bool` | Check if name is already registered. |
| `get_all_records() → Vec<(name, did, cid, gateways)>` | Get all records (4 fields). Used for DHT re-publishing. |
| `get_all_records_full() → Vec<NameRecord>` | Get all records (11 fields). Used for state snapshot generation. |
| `get_names_by_did(did) → Vec<NameRecord>` | Get all names owned by a DID. |

### 3.7 `did.rs` — Decentralised Identifiers

**DidDocument:**

```rust
pub struct DidDocument {
    pub id: String,                          // "did:feedo:{public_key_hex}"
    pub verification_method: Vec<VerificationMethod>,
    pub authentication: Vec<String>,
    pub service: Vec<ServiceEndpoint>,
    pub created: String,
    pub updated: String,
}
```

**Signature verification** (`verify_signature`):
- **Input**: Hex-encoded public key (with or without `0x` prefix), message bytes, hex-encoded signature
- **Algorithm**: secp256k1 ECDSA via `libsecp256k1`
- **Returns**: `true` if signature is valid, `false` otherwise

**DidManager** — Sled-backed DID document store:
- `insert_document(doc)`: Serializes to JSON, stores under `did:did:{id}` key
- `get_document(did)`: Retrieves and deserializes DID document

### 3.8 `replay.rs` — State Bootstrap

Two bootstrap modes:

| Function | Mode | When used |
|----------|------|-----------|
| `replay_from_snapshot(snapshot, name_db, did_manager, ledger)` | Fast | Node starts and finds a `/snapshot/{epoch}` record in DHT |
| `replay_from_dht(name_db, did_manager, dht_records)` | Legacy fallback | No snapshot available — scan individual `/name/*` and `/did/*` DHT records |

**Snapshot replay steps:**
1. Restore all `(wallet, balance)` pairs to the ledger
2. Restore all names (insert + update CID + update metadata)
3. Verify Merkle root: `ledger.generate_merkle_root()` → compare with `snapshot.merkle_root`
4. Log warning on mismatch (doesn't fail — node can sync via normal consensus)

### 3.9 `eth_bridge.rs` — Polygon Bridge

**Web3Bridge:**
- `new(rpc_url, ledger)`: Creates provider connection to Polygon RPC
- `fetch_committee() → Vec<String>`: Reads committee from `PporTreasury.sol` on-chain
- `start_event_listener()`: Background task that listens for `CreditClaimed` events and credits the ledger
- `start_auto_claim_daemon(rpc_url, private_key)`: Periodic auto-claim of accumulated credits from treasury

---

## 4. PBFT Consensus Protocol

### 4.1 Phase transitions

```
User submits tx
    │
    ▼
┌─────────────┐   2f+1 Prepare    ┌───────────┐   2f+1 Commit    ┌───────────┐
│ PrePrepare  │ ────────────────→ │  Prepare  │ ───────────────→ │  Commit   │ ──→ Finalized
│ (leader)    │                   │           │                  │           │
└─────────────┘                   └───────────┘                  └───────────┘
```

1. **PrePrepare**: Leader proposes transaction → sends `PbftMessage { phase: PrePrepare, tx_hash, tx_type }` to committee
2. **Prepare**: Committee members validate the transaction data → each sends Prepare vote
3. When 2f+1 Prepare votes collected → phase transitions to Commit
4. **Commit**: Committee members commit → each sends Commit vote
5. When 2f+1 Commit votes collected → phase transitions to Finalized
6. **Finalized**: Transaction is executed (name inserted, CID updated, ledger debited), published to DHT, PporState archived

### 4.2 Quorum calculation

```
required_votes = (2 × committee_size / 3) + 1
```

| Committee size | Quorum (2f+1) | Fault tolerance (f) |
|----------------|---------------|---------------------|
| 1 (self-only) | 1 | 0 |
| 3 | 3 | 0 |
| 4 | 3 | 1 |
| 7 | 5 | 2 |
| 10 | 7 | 3 |
| 21 | 15 | 6 |

### 4.3 Reputation-weighted committee selection

Every epoch (10 minutes), a new committee of ≤21 validators is elected:

1. **Seed**: `SHA256(last_finalized_hash || current_epoch)` — deterministic, all nodes agree
2. **Score**: For each validator: `weighted_score = hash(seed || node_id) × reputation`
3. **Selection**: Top `min(total_validators, 21)` by weighted score
4. **Minimum**: Always at least 1 validator (self)

### 4.4 Transaction timeout

- **Constant**: `TX_TIMEOUT_SECS = 30` seconds
- **Penalty**: Non-voting committee members lose 3 reputation points (`REP_TIMEOUT`)
- **Cleanup**: Timed-out transactions are removed from active `states`

### 4.5 Phase 1: Direct request-response (CONSENSUS_DIRECT_MODE=true)

When enabled (default), PBFT votes go via direct libp2p request-response to each committee member instead of gossipsub flood. Gossipsub listener for `feedo_consensus_ppor` is kept for backward compatibility with old nodes.

### 4.6 Phase 1.5: State snapshots & garbage collection

At each epoch rotation:
- `generate_state_snapshot()`: captures all balances + names + Merkle root + signature
- Published to DHT as `/snapshot/{epoch}`
- `cleanup_finalized_states(2)`: removes archive entries older than 2 epochs
- Names are re-published to DHT with current epoch

---

## 5. Transaction Types

| Constant | Value | Description | Timeout | Fee |
|----------|-------|-------------|---------|-----|
| `TX_TYPE_DATA` | 0 | Generic data (reserved) | 30s | — |
| `TX_TYPE_MICRO_TX_BATCH` | 1 | Micro-transaction batch (reserved) | 30s | — |
| `TX_TYPE_SLASHING` | 2 | Validator slashing (reserved) | 30s | — |
| `TX_TYPE_NAME_REGISTRATION` | 3 | Register `.feedo` name | 30s | 100 credits |
| `TX_TYPE_UPDATE_CID` | 4 | Update CID + gateways | 30s | Free |
| `TX_TYPE_LEDGER` | 5 | Credit/debit ledger entry | 30s | Free |
| `TX_TYPE_UPDATE_METADATA` | 6 | Update title/description/icon | 30s | Free |

---

## 6. Configuration

All configuration via environment variables.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `HTTP_PORT` | u16 | `3000` | Axum HTTP server port |
| `GRPC_PORT` | u16 | `50051` | Tonic gRPC server port |
| `P2P_PORT` | u16 | `8041` | libp2p QUIC listener port (UDP) |
| `DB_DIR` | string | `consensus_db` | Database directory (Sled + SQLite + peer_key.bin) |
| `NODE_WALLET_ADDRESS` | string | `0x00...00` | Ethereum wallet address (committee identity) |
| `NODE_PRIVATE_KEY` | hex | auto-generated | Ed25519 64-byte hex key for P2P identity |
| `EPOCH_DURATION_SECS` | u64 | `600` | Epoch duration in seconds (10 min) |
| `BOOTSTRAP_NODES` | string | (empty) | Comma-separated multiaddrs of existing nodes |
| `CONSENSUS_DIRECT_MODE` | bool | `true` | Phase 1: send PBFT via direct request-response instead of gossipsub |
| `ETH_RPC_URL` | string | `https://polygon-rpc.com` | Polygon RPC endpoint for on-chain committee |

---

## 7. HTTP API Reference

Base URL: `http://{host}:{HTTP_PORT}` (default `http://127.0.0.1:3000`)

### 7.1 Register DID

```
POST /did/register
Content-Type: application/json
```

**Request:** `{ "public_key": "0x..." }`

**Response:** `200 OK` — `{ "did": "did:feedo:{public_key_hex}" }`

DID creation automatically credits 500,000 credits to the new DID.

### 7.2 Register Name

```
POST /name/register
Content-Type: application/json
```

**Request:**
```json
{
    "name": "my-site.feedo",
    "did": "did:feedo:abc123...",
    "public_key": "0x...",
    "signature": "0x..."
}
```

**Validation:**
- Signature must be valid ECDSA over `name || did` bytes
- DID must exist (local or DHT)
- Balance must be ≥ 100 credits
- Name must not already exist

**Response:**
- `200 OK` — `{ "success": true, "error": null }`
- `200 OK` — `{ "success": false, "error": "Invalid signature" }` / `"Name already exists"` / `"Insufficient credits"` / `"DID not found"`

### 7.3 Update CID

```
POST /name/update_cid
Content-Type: application/json
```

**Request:**
```json
{
    "name": "my-site.feedo",
    "cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
    "signature": "0x...",
    "gateways": ["http://gateway1.feedo.ink"]
}
```

**Validation:** Signature must be valid ECDSA over `name || cid` bytes, verified against the DID's public key.

**Response:** `200 OK` — `{ "success": true/false, "error": "..." }`

### 7.4 Update Metadata

```
POST /name/update_metadata
Content-Type: application/json
```

**Request:**
```json
{
    "name": "my-site.feedo",
    "title": "My Website",
    "description": "A cool site",
    "icon_cid": "bafybei...",
    "public_key": "0x...",
    "signature": "0x..."
}
```

All fields except `name`, `public_key`, and `signature` are optional.

### 7.5 Resolve Name

```
GET /resolve/:name
```

**Response:** `200 OK` — JSON:
```json
{
    "did": "did:feedo:abc123...",
    "cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
    "gateways": ["http://gateway1.feedo.ink"],
    "epoch": 5,
    "finalized_at": 1783539480,
    "title": "My Website",
    "description": "A cool site",
    "icon_cid": "bafybei...",
    "created_at": 1783530000,
    "updated_at": 1783539480
}
```

Returns `null` (JSON null) if name not found. Merges local SQLite data with DHT data (preferring DHT when fresher).

### 7.6 Reverse CID Lookup

```
GET /resolve_cid/:cid
```

**Response:** `200 OK` — `"my-site.feedo"` or `null`

### 7.7 DID Balance

```
GET /did/:did/balance
```

**Response:** `200 OK` — `{ "balance_credits": 500000 }` or `null` if DID not found and balance is 0.

### 7.8 DID Names List

```
GET /did/:did/names
```

**Response:** `200 OK` — JSON array:
```json
[
    {
        "domain": "my-site.feedo",
        "cid": "bafybei...",
        "title": "My Website",
        "description": "A cool site",
        "icon_cid": "bafybei...",
        "created_at": 1783530000,
        "updated_at": 1783539480
    }
]
```

---

## 8. gRPC API

Service: `ConsensusService` (defined in `shared-proto`)

| Method | Request | Response | Description |
|--------|---------|----------|-------------|
| `VerifyUploadRights` | `VerifyUploadRequest { user_did, file_hash }` | `VerifyUploadResponse { is_allowed, reason }` | Check if DID has upload rights (balance > 0 + DID exists) |
| `ReportMissingChunk` | `MissingChunkRequest` | `MissingChunkResponse { reported }` | Stub — always returns `reported: true` |
| `GetActiveValidators` | `Empty` | `ValidatorList { validators }` | Stub — returns empty list |
| `ResolveName` | `ResolveNameRequest { name }` | `ResolveNameResponse { file_hash, found }` | Resolve name → CID (returns only from local SQLite) |

gRPC server listens on `0.0.0.0:{GRPC_PORT}` (default 50051).

---

## 9. P2P Protocol Details

### 9.1 Kademlia DHT key scheme

| Key pattern | Content | Purpose |
|-------------|---------|---------|
| `{name}` (e.g., `test.feedo`) | JSON `ResolveRes` | Name resolution records |
| `did:feedo:{hex}` | JSON `DidDocument` | DID document storage |
| `/reputation/{wallet}` | JSON `ReputationRecord` | Validator reputation scores |
| `/snapshot/{epoch}` | JSON `StateSnapshot` | State snapshots for fast bootstrap |

Records are stored with `Quorum::One`.

### 9.2 gossipsub topics

| Topic | Message format | Purpose |
|-------|---------------|---------|
| `feedo_peer_announce` | JSON `PeerAnnounce` | Node discovery: wallet→PeerId mapping |
| `feedo_consensus_ppor` | Protobuf `PbftMessage` | PBFT vote propagation (backward compat, Phase 1) |
| `feedo_name_txs` | JSON `NameRegistrationTx` | Name registration broadcast (legacy) |
| `feedo_update_cid_txs` | JSON `UpdateCidTx` | CID update broadcast (legacy) |
| `feedo_ledger_txs` | JSON `LedgerTx` | Ledger transaction broadcast (legacy) |
| `feedo_update_metadata_txs` | JSON `UpdateMetadataTx` | Metadata update broadcast (legacy) |
| `feedo_name_registrations` | — | Reserved (not actively used) |
| `feedo_did_updates` | — | Reserved (not actively used) |

### 9.3 request-response protocol

- **Protocol ID**: `/feedo-consensus/1.0.0`
- **Serialisation**: JSON with enum tagging (`#[serde(tag = "type")]`)
- **PbftMessage encoding**: protobuf → base64 for transport
- **Use cases**:
  - `TxRelay`: Send new transaction to committee members for PBFT processing
  - `PbftVote`: Send PBFT phase votes (PrePrepare/Prepare/Commit/Finalized) directly between validators

---

## 10. Testing

### 10.1 2-node integration test

Located in `tests/integration_test.rs`. Spawns 2 real consensus-node processes.

```bash
cargo build --bin consensus-node
cargo test --test integration_test -- --nocapture --test-threads=1
```

**Test cases (7):**

| # | Test | Description |
|---|------|-------------|
| 1 | DID Registration | Register DID via Node1, verify DID format |
| 2 | DID Balance | Check initial balance (500,000 credits) |
| 3 | Name Registration | Register name with signature, verify success |
| 4 | Resolve Name | Both Node1 and Node2 resolve the name correctly |
| 5 | CID Update | Update CID + gateways, verify on both nodes |
| 6 | Verify CID | Poll both nodes until CID matches expected value |
| 7 | Fault Tolerance | Kill Node2, register new name on Node1, verify Node1 still works |

### 10.2 25-node integration test

Located in `tests/integration_test_25.rs`. Spawns 25 real processes, tests epoch rotation and fault tolerance.

```bash
cargo build --bin consensus-node
cargo test --test integration_test_25 -- --nocapture --test-threads=1 --ignored
```

**Test cases (7, ~90 seconds):**

| # | Test | Description |
|---|------|-------------|
| 1 | DID Registration | Register DID via Node0 |
| 2 | Name Registration | Register name with signature |
| 3 | Resolve on All 25 Nodes | All 25 nodes resolve the name (≥20 must succeed) |
| 4 | CID Update via Node12 | Update CID through a middle node, verify propagation (≥18 nodes) |
| 5 | Epoch Rotation | Wait for epoch ≥ 1, verify epoch field in resolve (≥15 nodes) |
| 6 | Multi-Epoch | Wait 15s for next epoch, register second name, verify epoch in response |
| 7 | Fault Tolerance | Kill 5 nodes (20-24), register third name, verify 20/20 surviving nodes resolve it |

**Configuration for 25-node test:**
- `EPOCH_DURATION_SECS=10` (10 seconds per epoch)
- `NODE_DISCOVERY_TIMEOUT=40s`
- Each node gets unique `DB_DIR`, `P2P_PORT`, `HTTP_PORT`, `NODE_WALLET_ADDRESS`

### 10.3 Unit tests

Located in `did.rs` inline `#[cfg(test)]` module:

| Test | Description |
|------|-------------|
| `test_verify_signature` | Tests secp256k1 signature verification (ECDSA) |

---

## 11. Dependencies

| Crate | Version | Why |
|-------|---------|-----|
| `axum` | 0.7 | HTTP server framework |
| `tonic` | 0.12 | gRPC server framework |
| `shared-proto` | 0.1.0 (local) | Shared protobuf definitions for gRPC |
| `libp2p` | 0.53 | P2P networking: gossipsub, Kademlia DHT, request-response, QUIC, identify, mdns |
| `prost` | 0.13 | Protobuf runtime (for shared-proto) |
| `sled` | 0.34 | Embedded persistent key-value store (ledger, DID manager) |
| `rusqlite` | 0.31 | SQLite bindings (name registry) |
| `ethers` | 2.0 | Ethereum/Polygon RPC client (on-chain committee, event listener) |
| `rs_merkle` | 1.4 | Merkle tree implementation (state snapshots, Merkle root) |
| `serde` + `serde_json` | 1.0 | Serialization for all JSON data structures |
| `sha2` | 0.10 | SHA-256 hashing (transaction hashes, committee seed) |
| `ed25519-dalek` | 2.2 | Ed25519 key management for P2P identity |
| `secp256k1` | 0.28 | secp256k1 ECDSA signing (PBFT votes, snapshot signatures) |
| `hex` | 0.4 | Hex encoding for hashes and signatures |
| `base64` | 0.22 | Base64 encoding for protobuf-in-JSON transport |
| `tokio` | 1.35 | Async runtime (full features) |
| `tokio-stream` | 0.1 | Stream wrappers for libp2p swarm events |
| `futures` | 0.3 | StreamExt for swarm event loop |
| `tower-http` | 0.6 | CORS middleware for Axum |
| `reqwest` | 0.11 | HTTP client (Ethereum RPC calls) |
| `rand` | 0.8 | Random number generation |
| `async-trait` | 0.1 | Async trait support for gRPC service impl |

---

## 12. Known Issues & Future Work

### 12.1 Known issues

| Issue | Impact | Fix planned |
|-------|--------|-------------|
| **`test_verify_signature` may fail** | ECDSA signature format mismatch (`InvalidLength(64)`). Does not affect production. | Pre-existing — not related to Phase 1/1.5 |
| **Pre-existing dead_code warnings** | `eth_bridge`, `ppor_manager`, `swarm_tx` fields in `MyConsensusService` are never read. Cosmetic. | Clean up in future refactor |
| **Self-only committee** | When no on-chain committee is available, node falls back to self-only (single validator). | Expected behaviour for test/dev environments |
| **Gossipsub backward-compat topics** | Legacy `feedo_name_txs` etc. still use gossipsub for broadcasting. Phase 1 only changed PBFT votes. | Phase 2 will also migrate these to direct request-response |

### 12.2 Roadmap

See [CONSENSUS_ROADMAP.md](./CONSENSUS_ROADMAP.md) for the full 4-phase scaling plan.

| Phase | Status | Key deliverables |
|-------|--------|-----------------|
| **Phase 1** | ✅ Done | Direct request-response PBFT instead of gossipsub flood |
| **Phase 1.5** | ✅ Done | State snapshots, garbage collection, fast node bootstrap |
| **Phase 2** | Planned | Transaction-type sharding (parallel subcommittees) |
| **Phase 3** | Planned | Namespace-based sharding for names |
| **Phase 4** | Planned | DAG-based mempool + asynchronous consensus |