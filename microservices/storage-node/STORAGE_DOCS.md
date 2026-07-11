# Storage Node — Technical Documentation

> **Version**: 0.1.0 (Phase 1 complete)
> **Language**: Rust (edition 2024)
> **Last updated**: 2026-07-11

---

## 1. Overview

The **storage-node** is a decentralised byte-storage microservice in the Feedo ecosystem. It stores arbitrary data — websites (HTML/CSS/JS), social posts, user profiles, and generic blob files — across a P2P network using **erasure coding** and a **Kademlia Distributed Hash Table (DHT)**.

### Key capabilities

| Capability | Description |
|------------|-------------|
| **Erasure coding** | Reed-Solomon 30+15 (45 shards, 50% overhead). Any 30 of 45 shards can reconstruct the original file. |
| **Kademlia DHT** | Shards are distributed across peer nodes via libp2p Kademlia with O(log n) lookup. |
| **4 storage classes** | `Site`, `SocialPost`, `Profile`, `Blob` — each with independent quotas and (future) encoding policies. |
| **Flexible quotas** | Per-class byte quotas configured via environment variables. Backpressure (HTTP 507) instead of hard shutdown. |
| **Self-healing** | Reactive repair of lost shards on decode failure (proactive mode planned for Phase 3). |
| **Multi-protocol** | HTTP REST + gRPC + gossipsub pub/sub + WebSocket. |

### High-level architecture

```
┌──────────────────────────────────────────────────────────┐
│                    External Clients                       │
│         HTTP (axum)          gRPC (tonic)                 │
└──────────────┬──────────────────┬────────────────────────┘
               │                  │
┌──────────────▼──────────────────▼────────────────────────┐
│                      main.rs                              │
│  AppState { swarm_tx, recent_hashes, gossip_tx,           │
│             quota_manager }                               │
│  • handle_upload / handle_download / handle_delete         │
│  • handle_json_ingest / handle_batch_json_ingest          │
│  • handle_quota / handle_publish / handle_subscribe       │
│  • MyStorageService (gRPC)                                │
└──────────────────────┬───────────────────────────────────┘
                       │ mpsc channel (SwarmCommand)
┌──────────────────────▼───────────────────────────────────┐
│                   swarm_loop.rs                           │
│  run_swarm() — single-threaded event loop                 │
│  ┌──────────────────────────────────────────────────┐    │
│  │  tokio::select! {                                 │    │
│  │    swarm events  (Kademlia / gossipsub / req-resp)│    │
│  │    command_rx    (DhtUpload / DhtDownload / ...)   │    │
│  │  }                                                │    │
│  └──────────────────────────────────────────────────┘    │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │ network  │  │  quota   │  │  peer_   │  │ (future: │ │
│  │   .rs    │  │   .rs    │  │ cache.rs │  │  gc.rs)  │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │
└──────────────────────────────────────────────────────────┘
```

---

## 2. Architecture

### 2.1 Protocol stack

```
┌─────────────────────────────────┐
│  HTTP REST  │  gRPC  │  WebSocket │   ← Application layer
├─────────────────────────────────┤
│  axum (0.7) │ tonic (0.12)       │   ← Frameworks
├─────────────────────────────────┤
│  libp2p (0.53)                   │   ← P2P networking
│  ├─ Kademlia DHT (record store)  │
│  ├─ gossipsub (pub/sub)          │
│  ├─ request-response (CBOR)      │
│  ├─ identify + mdns (discovery)  │
│  ├─ QUIC (UDP) + TCP (fallback)  │
│  └─ noise + yamux (encryption)   │
├─────────────────────────────────┤
│  Sled (embedded KV store)        │   ← Persistent storage
├─────────────────────────────────┤
│  Reed-Solomon erasure coding     │   ← Data redundancy
└─────────────────────────────────┘
```

### 2.2 Data flow: Upload

```
Client
  │ POST /upload (multipart) + X-Feedo-Storage-Class header
  ▼
main.rs: handle_upload()
  │ 1. Extract storage_class from header (default: Blob)
  │ 2. Read multipart body → Vec<u8>
  │ 3. quota_manager.check_and_reserve(class, len) → Ok / Err(507)
  │ 4. Send SwarmCommand::DhtUpload(data, class, reply_channel)
  ▼
swarm_loop.rs: DhtUpload handler
  │ 1. SHA256(data) → file_hash
  │ 2. encode_data(data) → 45 shards (30 data + 15 parity)
  │ 3. peer_cache.top_n_addrs(45) → round-robin target peers
  │ 4. For each shard i:
  │    - Build chunk key: "{file_hash}_chunk_{i}"
  │    - If peer != local → req_resp StoreShard
  │    - If peer == local → kademlia.put_record(Quorum::One)
  │ 5. Build Manifest { file_hash, size, storage_class, shards: HashMap<i, PeerId> }
  │ 6. kademlia.put_record("{file_hash}_manifest", Quorum::One)
  │ 7. Reply with file_hash via oneshot channel
  ▼
main.rs: Return file_hash to client as 200 OK
```

### 2.3 Data flow: Download

```
Client
  │ GET /download/:hash
  ▼
main.rs: handle_download()
  │ Send SwarmCommand::DhtDownload(hash, reply_channel)
  ▼
swarm_loop.rs: DhtDownload handler
  │ 1. Look up "{hash}_manifest" in local HybridStore
  │ 2. If found → deserialise Manifest
  │ 3. For each (index, peer_id_str) in manifest.shards:
  │    - If peer == local → read from local store
  │    - If peer != local → req_resp FetchShard
  │ 4. Wait until received ≥ DATA_SHARDS (30)
  │ 5. decode_data(shards, original_size) → Vec<u8>
  │ 6. If decode fails → do_self_healing() → retry
  │ 7. Reply with data via oneshot channel
  │
  │ If manifest not local:
  │    - kademlia.get_record("{hash}_manifest")
  │    - Wait for Kademlia OutboundQueryProgressed → GetRecord result
  │    - Then proceed with step 3
  ▼
main.rs: Return Vec<u8> as 200 OK (or 404 if not found)
```

### 2.4 Module map

| File | Lines | Role |
|------|-------|------|
| `main.rs` | 452 | Entry point: HTTP/gRPC servers, key loading, swarm init, route definitions |
| `swarm_loop.rs` | 550 | Core event loop: handles all SwarmCommand variants, Kademlia/gossipsub/req-resp events |
| `network.rs` | 148 | Reed-Solomon encode/decode, Manifest struct, HybridStore, StorageBehaviour |
| `quota.rs` | 331 | StorageClass enum, PerClassQuota (AtomicU64), QuotaConfig, StorageQuotaManager |
| `peer_cache.rs` | 78 | JSON-file-based peer discovery cache with EMA scoring |
| `crdt.rs` | 189 | **Not compiling** — CRDT conflict resolution (LwwMap, AwOrSet), depends on missing modules |
| `old_main_p2p.rs` | — | **Dead code** — previous P2P implementation, kept for reference |

---

## 3. Module Reference

### 3.1 `main.rs` — Entry Point

**Key structures:**

```rust
// Shared application state, cloneable for Axum extractors
pub struct AppState {
    pub swarm_tx: mpsc::UnboundedSender<SwarmCommand>,
    pub recent_hashes: Arc<Mutex<Vec<String>>>,
    pub gossip_tx: broadcast::Sender<(String, Vec<u8>)>,
    pub quota_manager: Arc<StorageQuotaManager>,
}

// gRPC service implementation
pub struct MyStorageService {
    pub swarm_tx: mpsc::UnboundedSender<SwarmCommand>,
}

// JSON ingest payload (used by /api/v1/ingest/post and /batch)
pub struct IngestPayload {
    pub hash_id: String,
    pub author: String,
    pub text: String,
    pub target_hash: Option<String>,
    pub signature: String,
    pub metadata: serde_json::Value,
    pub ttl_days: Option<u32>,           // Declared but NOT enforced (Phase 3)
    pub storage_class: Option<String>,    // Phase 1: "site"|"social_post"|"profile"|"blob"
}
```

**Key functions:**

| Function | Description |
|----------|-------------|
| `main()` | Initialises Sled DB, QuotaManager, libp2p swarm, spawns swarm loop, starts HTTP + gRPC servers |
| `handle_upload()` | Multipart file upload. Reads `X-Feedo-Storage-Class` header → checks quota → sends `DhtUpload` |
| `handle_json_ingest()` | Single JSON post ingest. Defaults to `SocialPost` class |
| `handle_batch_json_ingest()` | Batch JSON ingest. Defaults to `Profile` class. Skips items that exceed quota |
| `handle_download()` | Download by hash → sends `DhtDownload` |
| `handle_delete()` | Delete by hash → sends `DhtDelete` |
| `handle_quota()` | Returns per-class usage JSON |
| `handle_recent_files()` | Returns list of recently uploaded hashes |
| `handle_publish()` | Publishes arbitrary JSON to a gossipsub topic |
| `handle_subscribe()` | Upgrades to WebSocket, subscribes to a gossipsub topic, relays messages |
| `load_keypair_from_env_or_file()` | Loads Ed25519 key from `NODE_PRIVATE_KEY` env var or `{DB_DIR}/peer_key.bin` file |

**Initialisation flow in `main()`:**

1. Open/create Sled database at `DB_DIR`
2. Create `StorageQuotaManager` from env vars (`QuotaConfig::from_env()`)
3. Build libp2p swarm: QUIC + TCP transport, noise encryption, yamux muxing
4. Configure behaviours: gossipsub (topic `storage_announcements`), Kademlia (server mode), identify, mdns, request-response (`/feedo/chunks/1.0.0`)
5. Listen on `P2P_PORT` (UDP/QUIC)
6. Dial bootstrap nodes from `BOOTSTRAP_NODES`
7. Spawn `swarm_loop::run_swarm()` in a separate Tokio task
8. Start gRPC server on `GRPC_PORT` and HTTP server on `HTTP_PORT`
9. `tokio::select!` — runs until either server exits

### 3.2 `swarm_loop.rs` — Core Event Loop

**Key types:**

```rust
pub enum SwarmCommand {
    DhtUpload(Vec<u8>, StorageClass, oneshot::Sender<String>),
    DhtDownload(String, oneshot::Sender<Option<Vec<u8>>>),
    DhtDelete(String),
    SavePeerCache,
    GcPeerCache(u64),        // days
    AnnouncePeer,
    Publish(String, Vec<u8>), // topic, data
    SubscribeTopic(String),
}

pub struct FetchState {
    pub sender: Option<oneshot::Sender<Option<Vec<u8>>>>,
    pub shards: Vec<Option<Vec<u8>>>,
    pub received: usize,
    pub failed: usize,
    pub original_size: usize,
    pub manifest: Option<Manifest>,
}

pub struct PeerAnnounce {
    pub peer_id: String,
    pub listen_addrs: Vec<String>,
    pub timestamp: u64,
    pub public_key: Option<String>,
    pub storage_status: Option<String>,     // "OK" or "Full" (legacy)
    pub quota_status: Option<Value>,         // Phase 1: per-class usage JSON
    // ...
}
```

**Event handling in `run_swarm()`:**

| Event | Handler |
|-------|---------|
| `SwarmEvent::NewListenAddr` | Logs the listening address |
| `SwarmEvent::ConnectionEstablished` | Updates `peer_cache` with success |
| `Kademlia::OutboundQueryProgressed` (GetRecord) | Either manifest found → start shard downloads; or individual shard found → accumulate |
| `Kademlia::RoutingUpdated` | Prints new peer, updates `peer_cache` |
| `Gossipsub::Message` (topic `storage_announcements`) | Deserialises `PeerAnnounce`, validates timestamp, adds addresses to Kademlia routing table |
| `ReqResp::Message::Request::StoreShard` | Puts chunk into local Kademlia store, replies `StoreOk` |
| `ReqResp::Message::Request::FetchShard` | Reads chunk from local store, replies `ShardData` |
| `ReqResp::Message::Request::FetchManifest` | Reads manifest from local store, replies `ManifestData` |
| `ReqResp::Message::Response::ShardData` | Accumulates shard, triggers decode when ≥30 received |
| `ReqResp::Event::OutboundFailure` | Counts as failed shard; if total ≥45, aborts fetch |

**Self-healing (`do_self_healing()`):**
- Triggered reactively when `decode_data()` fails despite having ≥30 shards
- Re-encodes the successfully decoded data → redistributes only the missing shards
- Updates manifest with new shard locations
- Stores manifest locally via `kademlia.store_mut().put()`

### 3.3 `network.rs` — Erasure Coding & DHT Store

**Constants:**

```rust
pub const DATA_SHARDS: usize = 30;
pub const PARITY_SHARDS: usize = 15;
pub const TOTAL_SHARDS: usize = 45;
```

**Manifest (v2, Phase 1):**

```rust
pub struct Manifest {
    pub file_hash: String,                           // SHA256 hex
    pub size: usize,                                 // Original file size in bytes
    pub storage_class: Option<String>,               // Phase 1: "site"|"social_post"|"profile"|"blob"
    pub shards: HashMap<usize, String>,              // index → PeerId string
}
```

Backward compatibility: `storage_class` is `Option<String>` with `#[serde(default, skip_serializing_if = "Option::is_none")]`. Old manifests without this field deserialise as `None`.

**Request/Response protocol (`/feedo/chunks/1.0.0`):**

```rust
pub enum DirectRequest {
    Handshake { challenge: String },
    StoreShard { chunk_key: String, data: Vec<u8> },
    FetchShard { chunk_key: String },
    FetchManifest { file_hash: String },
}

pub enum DirectResponse {
    HandshakeResponse(Vec<u8>),
    StoreOk,
    ShardData(Option<Vec<u8>>),
    ManifestData(Option<Manifest>),
}
```

**Reed-Solomon encoding (`encode_data()`):**
1. Create `ReedSolomon` instance with DATA_SHARDS=30, PARITY_SHARDS=15
2. Pad input to multiple of DATA_SHARDS, split into 30 data shards
3. Encode → 45 total shards (30 data + 15 parity)
4. Any 30 of 45 shards can reconstruct the original

**Reed-Solomon decoding (`decode_data()`):**
1. Receive `Vec<Option<Vec<u8>>>` — Some(shard) or None (missing)
2. Call `rs.reconstruct()` — fills in missing shards
3. Concatenate first DATA_SHARDS shards, truncate to `original_len`

**HybridStore:**
- Implements `libp2p::kad::store::RecordStore`
- Two-tier: in-memory `MemoryStore` (size configurable via `DHT_RAM_CACHE_LIMIT`) + persistent `sled::Db`
- On `get()`: checks memory first, then sled, then returns None
- On `put()`: checks `storage_full` flag (legacy), writes to both memory and sled
- The `storage_full` flag is kept for backward compatibility but is always `false` after Phase 1 — quota enforcement happens at the HTTP handler level

### 3.4 `quota.rs` — Storage Classes & Quota Management

**StorageClass enum:**

```rust
pub enum StorageClass {
    Site,        // HTML/CSS/JS — highest priority, indefinite
    SocialPost,  // Nostr posts — lowest priority, temporary
    Profile,     // Nostr profiles — medium priority
    Blob,        // Arbitrary files — paid cloud storage
}
```

Parsing: accepts `"site"`, `"social_post"` / `"social"` / `"post"`, `"profile"`, `"blob"` / `"file"` / `"object"` (case-insensitive). Default: `Blob`.

**PerClassQuota:**
- Lock-free atomic counter using `AtomicU64` with CAS loop
- `try_reserve(size) → bool`: atomically checks and increments if within limit
- `release(size)`: decrements counter (used on delete/GC or encoding failure)
- Thread-safe — safe to call from multiple tasks concurrently

**QuotaConfig:**
- Read from environment variables with sensible defaults:
  - `QUOTA_SITES_GB` → default 100 GB
  - `QUOTA_BLOBS_GB` → default 1 TB
  - `QUOTA_SOCIAL_MB` → default 500 MB
  - `QUOTA_PROFILES_MB` → default 100 MB
- Accepts floating-point values (e.g., `QUOTA_SOCIAL_MB=0.5` for 512 KB)

**StorageQuotaManager:**
- `check_and_reserve(class, size) → Result<(), String>`: atomically reserves bytes for a class. Returns `Err` with human-readable message if quota exceeded (prints warning to stderr).
- `release(class, size)`: returns bytes to the pool.
- `usage_all() → Value`: returns JSON snapshot for all 4 classes (used_bytes, max_bytes, human-readable MB strings).

### 3.5 `peer_cache.rs` — Peer Discovery Cache

**PeerCacheEntry:**
- `peer_id`: PeerId string
- `multiaddrs`: list of known addresses
- `last_seen_unix`: timestamp of last contact
- `success_count` / `fail_count`: connection outcome counters
- `score`: exponentially weighted moving average (EMA): `score = score*0.8 + 0.2*(success+1)` on success, `score = score*0.9 - 0.1*(fail+1)` on failure

**PeerCache:**
- Serialised to/from `peer_cache.json`
- `add_or_update(peer_id, addrs, success)`: inserts or updates entry, updates score
- `top_n_addrs(n)`: returns addresses of top-N peers by score (used for shard distribution)
- `gc(days)`: removes peers not seen for more than N days

**Known limitation:** JSON-file-based cache does not scale beyond ~100 nodes. Phase 3 will replace this with Kademlia's built-in routing table.

### 3.6 `crdt.rs` — Conflict-Free Replicated Data Types (NOT COMPILING)

**Status:** This module references `crate::proto::feedo::CrdtOperation` and `crate::did::verify_signature` which do not exist in the current codebase. The module will not compile and is excluded from the build.

**Intended functionality (future):**
- `LwwMapState`: Last-Writer-Wins map for key-value state with timestamp-based conflict resolution
- `AwOrSetState`: Add-Wins Observed-Remove set for collection CRDTs
- `CrdtManager`: processes operations, checks ACL (`did:feedo:` ownership), verifies Ed25519 signatures, stores operation log in Sled

---

## 4. Configuration

All configuration is via environment variables.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DB_DIR` | path | `storage_db` | Sled database directory (also stores `peer_key.bin`) |
| `HTTP_PORT` | u16 | `3001` | Axum HTTP server port |
| `GRPC_PORT` | u16 | `50052` | Tonic gRPC server port |
| `P2P_PORT` | u16 | `8040` | libp2p QUIC listener port (UDP) |
| `BOOTSTRAP_NODES` | string | (none) | Comma-separated multiaddrs, e.g. `/ip4/1.2.3.4/udp/8040/quic-v1/p2p/12D3...` |
| `NODE_PRIVATE_KEY` | hex | (auto-generated) | Ed25519 64-byte hex-encoded private key. If not set, reads from `{DB_DIR}/peer_key.bin` or generates new. |
| `DHT_RAM_CACHE_LIMIT` | usize | `1000` | Max records in libp2p MemoryStore (LRU eviction). |
| `QUOTA_SITES_GB` | f64 | `100` | Max gigabytes for `Site` storage class |
| `QUOTA_BLOBS_GB` | f64 | `1000` | Max gigabytes for `Blob` storage class |
| `QUOTA_SOCIAL_MB` | f64 | `500` | Max megabytes for `SocialPost` storage class |
| `QUOTA_PROFILES_MB` | f64 | `100` | Max megabytes for `Profile` storage class |

---

## 5. HTTP API Reference

Base URL: `http://{host}:{HTTP_PORT}` (default `http://127.0.0.1:3001`)

### 5.1 Upload file

```
POST /upload
Content-Type: multipart/form-data
X-Feedo-Storage-Class: site|social_post|profile|blob  (optional, default: blob)
```

**Request body:** Multipart form with field `file` containing the file bytes.

**Response:**
- `200 OK` — plain text file hash (SHA256 hex string)
- `400 Bad Request` — no file provided or invalid multipart
- `507 Insufficient Storage` — quota exceeded for the requested storage class

**Example:**
```bash
curl -X POST http://127.0.0.1:3001/upload \
  -H "X-Feedo-Storage-Class: site" \
  -F "file=@my-website.zip"
# → bf1fd1300fcfc0acc086986564f64e70c759a4d8bde5e05f57b740705ca7c875
```

### 5.2 Download file

```
GET /download/:hash
```

**Response:**
- `200 OK` — raw file bytes (`application/octet-stream`)
- `404 Not Found` — file not available in DHT (manifest not found or insufficient shards)

**Example:**
```bash
curl http://127.0.0.1:3001/download/bf1fd1300fcfc0acc086986564f64e70c759a4d8bde5e05f57b740705ca7c875 \
  --output restored.zip
```

### 5.3 Delete file

```
DELETE /delete/:hash
```

Deletes the manifest and all shards **locally**. Does NOT propagate deletion to other nodes (future: gossip-based GC in Phase 3).

**Response:** `200 OK` — `"Deleted locally"`

### 5.4 JSON ingest (single post)

```
POST /api/v1/ingest/post
Content-Type: application/json
```

**Request body:**
```json
{
    "hash_id": "unique-post-id",
    "author": "did:feedo:abc123...",
    "text": "Post content text",
    "target_hash": null,
    "signature": "hex-encoded-ed25519-signature",
    "metadata": {},
    "ttl_days": 30,
    "storage_class": "social_post"
}
```

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `hash_id` | Yes | — | Unique identifier for deduplication |
| `author` | Yes | — | DID of the author |
| `text` | Yes | — | Post content |
| `signature` | Yes | — | Ed25519 signature (hex) |
| `storage_class` | No | `social_post` | Storage class for quota tracking |
| `ttl_days` | No | `null` | Time-to-live in days (not yet enforced) |

**Response:** `200 OK` — file hash string

### 5.5 JSON batch ingest

```
POST /api/v1/ingest/batch
Content-Type: application/json
```

**Request body:** Array of `IngestPayload` objects (same schema as single ingest).

**Response:** `200 OK` — JSON array of file hashes. Items that fail quota check are silently skipped.

### 5.6 Quota status

```
GET /api/v1/quota
```

**Response:** `200 OK` — JSON:
```json
{
    "site":       { "used_bytes": 1048576, "max_bytes": 107374182400, "used_mb": "1.00", "max_mb": "102400.00" },
    "blob":       { "used_bytes": 0,       "max_bytes": 1099511627776, "used_mb": "0.00", "max_mb": "1048576.00" },
    "social_post":{ "used_bytes": 2048,    "max_bytes": 524288000,     "used_mb": "0.00", "max_mb": "500.00" },
    "profile":    { "used_bytes": 512,     "max_bytes": 104857600,     "used_mb": "0.00", "max_mb": "100.00" }
}
```

### 5.7 Recent files

```
GET /api/files/recent
```

**Response:** `200 OK` — JSON: `{ "hashes": ["abc123...", "def456..."] }`

Note: The recent hashes list is in-memory only and lost on restart.

### 5.8 Publish to gossipsub topic

```
POST /api/v1/pubsub/publish
Content-Type: application/json
```

**Request body:** `{ "topic": "my-topic", "data": { ... } }`

Publishes arbitrary JSON to a gossipsub topic. All subscribed peers receive the message.

### 5.9 Subscribe to gossipsub topic (WebSocket)

```
GET /api/v1/pubsub/subscribe/:topic
Upgrade: websocket
```

Upgrades to WebSocket. The node subscribes to the gossipsub topic and relays all received messages to the WebSocket client as binary frames.

---

## 6. gRPC API

Service: `StorageService` (defined in `shared-proto`)

| Method | Request | Response | Description |
|--------|---------|----------|-------------|
| `InternalFetchFile` | `FetchRequest { file_hash }` | stream `ChunkData { data }` | Fetch file by hash; returns single chunk or NOT_FOUND |
| `StreamNewUploads` | `Empty` | stream `NewFileEvent` | **Stub** — not yet implemented (empty channel) |

gRPC server listens on `0.0.0.0:{GRPC_PORT}` (default 50052).

---

## 7. P2P Protocol Details

### 7.1 Kademlia DHT key scheme

| Key pattern | Content | Purpose |
|-------------|---------|---------|
| `{hash}_manifest` | JSON-serialised `Manifest` | Maps file hash → shard locations |
| `{hash}_chunk_{i}` | Raw shard bytes | Individual erasure-coded shard (i = 0..44) |

Records are stored with `Quorum::One` (single copy). **Phase 3** will upgrade to `Quorum::Three` for manifest redundancy.

### 7.2 gossipsub

- **Topic**: `storage_announcements`
- **Message format**: JSON-serialised `PeerAnnounce`
- **Purpose**: Node discovery — peers announce their listen addresses, storage status, and (Phase 1) per-class quota snapshots
- **Validation**: Messages with timestamp >60s in the future or >1 hour in the past are ignored. The announce `peer_id` must match the gossipsub message source.

### 7.3 request-response protocol

- **Protocol ID**: `/feedo/chunks/1.0.0`
- **Serialisation**: CBOR (Concise Binary Object Representation)
- **Use cases**:
  - `StoreShard`: Upload node sends shard to a remote peer for storage
  - `FetchShard`: Download node requests a specific shard from a remote peer
  - `FetchManifest`: Node requests a manifest from a remote peer (fallback, normally fetched via Kademlia `get_record`)

### 7.4 Shard distribution algorithm

1. Get top-45 peers from `peer_cache.top_n_addrs(45)` sorted by score
2. Extract `PeerId` from each multiaddr
3. If no peers known → use `swarm.local_peer_id()` as fallback
4. For shard `i` (0..44): assign to `target_peers[i % target_peers.len()]` (round-robin)
5. Store mapping in Manifest as `shards: HashMap<usize, PeerId_string>`

### 7.5 Self-healing

- **Trigger**: `decode_data()` returns `Err` despite having ≥30 shards
- **Process**:
  1. Attempt to reconstruct data from available shards
  2. Re-encode to generate all 45 shards
  3. Identify missing shards (positions where `state.shards[i].is_none()`)
  4. Redistribute repaired shards using same round-robin algorithm
  5. Update manifest with new shard locations
  6. Store updated manifest locally
- **Limitation**: Purely reactive — only runs when a download fails. Phase 3 will add proactive periodic health checks.

---

## 8. Testing

### 8.1 Unit tests

Located in `quota.rs` (inline `#[cfg(test)]` module). 5 tests:

```bash
cargo test --manifest-path microservices/storage-node/Cargo.toml --bin storage-node -- quota::tests
```

| Test | What it verifies |
|------|-----------------|
| `test_storage_class_parse` | All valid string representations parse correctly; invalid returns error |
| `test_storage_class_default` | Default is `Blob` |
| `test_quota_reserve_and_release` | Atomic reserve within limit, exceed detection, release |
| `test_quota_independent_classes` | Exhausting one class does not affect others |
| `test_usage_all_json` | `usage_all()` returns valid JSON with all 4 classes |

### 8.2 Integration test

Located in `tests/integration_test.rs`. Spawns 2 real storage-node processes.

```bash
cargo build --bin storage-node
cargo test --test integration_test -- --nocapture --test-threads=1
```

**What it tests (11 test cases):**

| # | Test | Description |
|---|------|-------------|
| 1 | Upload to Node0 | Multipart upload, returns valid SHA256 hash |
| 2 | Download from Node0 | Retrieved data matches original |
| 3 | Delete from Node0 | Deleted file returns 404 |
| 4 | Upload to Node1 | Node1 accepts upload |
| 5 | Download from Node1 | Node1 serves its own file |
| 6 | Recent files API | Both nodes report recent hashes |
| 7 | Storage class header | Upload with `X-Feedo-Storage-Class: site` / `blob` |
| 8 | JSON ingest with class | Explicit and default storage_class in `/api/v1/ingest/post` |
| 9 | Batch ingest with class | Mixed storage_class in `/api/v1/ingest/batch` |
| 10 | Quota API | `GET /api/v1/quota` returns valid JSON with all 4 classes |
| 11 | Quota backpressure | Upload within quota succeeds (default quotas are large) |

**Cleanup:** Test databases (`test_storage_db0/`, `test_storage_db1/`) are removed before each run. Processes are killed via `Drop` guard.

---

## 9. Dependencies

| Crate | Version | Why |
|-------|---------|-----|
| `axum` | 0.7 | HTTP server framework (multipart + WebSocket support) |
| `tonic` | 0.12 | gRPC server framework |
| `shared-proto` | 0.1.0 (local) | Shared protobuf definitions for gRPC |
| `libp2p` | 0.53 | P2P networking: Kademlia DHT, gossipsub, request-response, QUIC, identify, mdns |
| `reed-solomon-erasure` | 6.0 | Galois field (2^8) Reed-Solomon encoding/decoding |
| `sled` | 0.34 | Embedded persistent key-value store (backing for Kademlia RecordStore) |
| `serde` + `serde_json` | 1.0 | Serialization for Manifest, PeerAnnounce, IngestPayload, peer cache |
| `sha2` | 0.10 | SHA-256 hashing for content addressing |
| `hex` | 0.4 | Hex encoding for hashes and signatures |
| `base64` | 0.22 | Base64 encoding for public keys in PeerAnnounce |
| `tokio` | 1.52 | Async runtime (full features) |
| `tokio-stream` | 0.1 | Stream wrappers for gRPC streaming responses |
| `futures` | 0.3 | StreamExt for swarm event loop |
| `tower-http` | 0.6 | CORS middleware for Axum |
| `prost` | 0.13 | Protobuf runtime (for shared-proto) |

**Dev dependencies:**

| Crate | Why |
|-------|-----|
| `reqwest` | HTTP client for integration tests (blocking + multipart) |
| `zip` | Create test zip files in memory |

---

## 10. Known Issues & Future Work

### 10.1 Known issues

| Issue | Impact | Fix planned |
|-------|--------|-------------|
| **`crdt.rs` does not compile** | Missing `proto::feedo` and `did` modules. CRDT operations unavailable. | TBD — needs shared-proto update |
| **`old_main_p2p.rs` is dead code** | Confusing for new contributors. | Remove or archive |
| **Manifest stored with `Quorum::One`** | Single point of failure — if the hosting node goes offline, the file cannot be located even if all shards are available. | Phase 3 |
| **Self-healing is reactive only** | Data loss is only detected when a user tries to download. Silent data loss can accumulate. | Phase 3 (proactive loop) |
| **TTL is declared but not enforced** | `ttl_days` field exists in `IngestPayload` but no garbage collection runs. Storage grows unboundedly. | Phase 3 |
| **Peer cache in JSON file** | Does not scale beyond ~100 nodes. Kademlia already maintains a routing table that could serve this purpose. | Phase 3 |
| **Fixed 30+15 Reed-Solomon for all data** | A 2 KB social post generates 45 shards (high overhead). A 500 MB video also generates only 45 shards (no parallelism). | Phase 2 |
| **No streaming upload/download** | Entire file must be buffered in memory before encoding. Entire file must be reassembled before serving. | Phase 5 |
| **No deduplication** | Identical files uploaded by different users are stored as separate copies. | Phase 5 |

### 10.2 Roadmap

See [STORAGE_ROADMAP.md](./STORAGE_ROADMAP.md) for the full 5-phase scaling plan.

| Phase | Status | Key deliverables |
|-------|--------|-----------------|
| **Phase 1** | ✅ Done (2026-07-11) | Flexible quotas + 4 storage classes |
| **Tokenomics** | Separate project | Pay-per-byte via `PporTreasury.sol` |
| **Phase 2** | Planned | Parameterised erasure coding + chunking for large files |
| **Phase 3** | Planned | TTL garbage collection + manifest redundancy (Quorum::Three) + proactive healing |
| **Phase 4** | Planned | Protocol extension layer — v2 API, SDKs (JS/Python/Rust/Dart) |
| **Phase 5** | Planned | Deduplication, streaming upload/download, proof-of-storage |

### 10.3 Unused imports (warnings)

The following warnings exist in the current codebase and are safe to ignore (or can be cleaned up with `cargo fix`):

- `main.rs`: `StreamProtocol`, `identity`, `kad`, `MessageAuthenticity`, `ValidationMode`, `StorageBehaviour`, `DirectRequest`, `DirectResponse`, `run_swarm`
- `swarm_loop.rs`: `PARITY_SHARDS`, `Quorum`