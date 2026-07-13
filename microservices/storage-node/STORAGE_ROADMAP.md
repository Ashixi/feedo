# Storage Node — Scalability Roadmap / Roadmap масштабування

> 🌐 **Language / Мова**: [🇺🇦 Українська](#uk) | [🇬🇧 English](#en)

<div id="en">

# Storage Node — Scalability Roadmap

> **Goal**: scale storage-node from the current 10 GB/node to unlimited volume, with different storage tiers for sites and files, and with the foundation for decentralized cloud storage (an AWS analogue for Web3).
>
> **Current problem**: 10 GB hard-limit per node, identical erasure coding for all data types (a 100 KB site and a potential 500 MB video both go through 30+15 RS), manifest without replication, TTL not enforced.

---

## Current State (baseline)

| Parameter | Value |
|-----------|-------|
| Confirmed node count | 2 (test `st_test.txt`) |
| Storage | Sled (embedded key-value) |
| Limit | **10 GB hard-coded**, checked every 60 sec (`main.rs` line 290) |
| Encoding | Reed-Solomon: 30 data + 15 parity = 45 shards (for **all** data types) |
| Distribution | Round-robin across peers from `peer_cache.json` |
| Manifest | One record in Kademlia DHT (single point of failure) |
| Self-healing | Reactive only (on failed decode) |
| TTL | Declared in JSON (30 days posts, 365 days profiles) but **not enforced** — data is not deleted |
| Data types | All the same — site, social post, profile are handled identically |
| Protocol | HTTP REST (`/upload`, `/download/:hash`, `/delete/:hash`) + gRPC + gossipsub pub/sub + WebSocket |
| Dead code | `old_main_p2p.rs` |

### Key Architectural Problems

1. **10 GB hard-limit**: the node simply stops accepting data after reaching the limit. No graceful degradation, no quotas for different data types.
2. **Same Erasure Coding for everything**: 30+15 (45 shards, 50% overhead) is applied to both a 2 KB JSON post and a potential 500 MB video file. For large files, this creates unnecessary network overhead without benefit.
3. **Manifest in DHT without replication**: one record on one node. If that node is offline — the file cannot be recovered, even if all shards are available.
4. **No TTL garbage collection**: `ttl_days` is passed in JSON on ingest, but no code deletes expired data. Storage grows uncontrollably.
5. **No interface for external protocol**: everything is hardcoded in HTTP handlers. Impossible to layer a separate cloud storage protocol without changing the core.
6. **Peer cache in JSON file**: doesn't scale to hundreds of nodes. Kademlia routing table already exists in libp2p, but is not used for this purpose.

---

## Phase 1: Flexible Quotas + Storage Classes ✅ DONE (2026-07-11)

**Goal**: Remove the 10 GB hard-limit, introduce separate quotas for different data types, lay the foundation for a future cloud protocol.

**Expected growth**: volume/node becomes configurable (∞ with operator quotas), storage class separation appears.

### What to Change

#### 1.1 `main.rs` — replace `storage_full` with `StorageQuotaManager`

- **Current code** (lines ~286-297): every 60 seconds checks `get_dir_size()`, if > 10 GB — sets `storage_full = true`. After this, the node stops accepting any data.
- **What to do**: Replace with `StorageQuotaManager` with separate quotas:
  - `QUOTA_SITES_GB` — sites (highest priority, indefinite storage)
  - `QUOTA_BLOBS_GB` — files/cloud storage (separate quota, paid)
  - `QUOTA_SOCIAL_MB` — posts (lowest priority, temporary)
  - `QUOTA_PROFILES_MB` — profiles (medium priority)
- When a quota is reached for a specific class — **not reject**, but backpressure (Warn log, metric for operator, slow down acceptance).
- The node operator decides: 100 GB for sites, 1 TB for files, 500 MB for posts.
- **Files**: `main.rs` — replace logic, new `quota.rs` — `StorageQuotaManager`.

#### 1.2 `main.rs` + `swarm_loop.rs` — introduce `StorageClass`

- **Current code**: all data is handled identically. No field distinguishing data type.
- **What to do**: Add `StorageClass` enum:
  - `Site` — HTML/CSS/JS sites (uploaded via `/upload` or `proxy_publish_feedo`)
  - `SocialPost` — Nostr posts (via `/api/v1/ingest/post`)
  - `Profile` — Nostr profiles (via `/api/v1/ingest/batch`)
  - `Blob` — arbitrary files (foundation for future cloud protocol)
- Client passes `storage_class` on upload (HTTP header `X-Feedo-Storage-Class` or field in JSON body).
- `IngestPayload` (line 123 `main.rs`) gets `storage_class` field.
- Manifest gets `storage_class` field.
- **Files**: `main.rs` — `StorageClass` enum + extend `IngestPayload`, `network.rs` — Manifest v2.

### Phase 1 Result

- Operator controls how much space to allocate for sites vs files
- Node doesn't "die" when limit is reached — only slows acceptance for the overflowing class
- Storage classes ready for Phase 2 (different encoding)
- Posts can be limited to 500 MB and automatically deleted (Phase 3), not consuming space for sites

---

## 🔶 Tokenomics (separate project)

> **Location**: between Phase 1 and Phase 2. Carefully designed, implemented as a separate file/project.

**Role in storage roadmap**: defines the economic pay-per-byte model via `PporTreasury.sol` (already exists). User deposits USDC on Polygon → gets quota for X GB/month. Node operators receive rewards for storage + bandwidth.

**Impact on storage-node**:
- Phase 2+ uses user balance to determine `storage_class=Blob` quota
- `StorageQuotaManager` considers not only local quotas but also global balance via gRPC to consensus-node
- Proof-of-Storage (Phase 5) integrates with treasury rewards

> **Note**: tokenomics is not part of this roadmap — it's a separate document. It is mentioned here only as an external dependency.

---

## Phase 2: Parameterized Erasure Coding + Chunking for Large Files

**Goal**: Different encoding parameters for different storage classes, support for files of any size via chunking.

**Expected growth**: efficient network usage (fewer shards for small data), support for files >100 MB without degradation.

### What to Change

#### 2.1 `swarm_loop.rs` — parameterize Reed-Solomon by `StorageClass`

- **Current code**: constants `DATA_SHARDS = 30`, `PARITY_SHARDS = 15`, `TOTAL_SHARDS = 45` used for all data.
- **What to do**: Replace constants with function `get_rs_params(class: StorageClass, file_size: usize) -> (usize, usize)`:
  - `Site` (indefinite storage, high importance): **30+15** (45 shards, overhead 50%, survives loss of 15 nodes)
  - `SocialPost` (temporary, low importance): **10+5** (15 shards, overhead 50%, survives loss of 5 nodes)
  - `Profile` (medium importance, easily recreated): **5+3** (8 shards, overhead 60%)
  - `Blob` ≤10 MB: **20+10** (30 shards, reliable file storage)
  - `Blob` 10-100 MB: chunk 5 MB each, each chunk **15+7** (22 shards)
  - `Blob` >100 MB: chunk 10 MB each, each chunk **20+10** (30 shards)
- **Files**: `swarm_loop.rs` — replace constants with function, `network.rs` — move or remove constants.

#### 2.2 New `chunking.rs` — split large files into chunks

- **Current code**: entire file encoded as one block. For 500 MB video this means 500 MB in memory + 45 shards.
- **What to do**: Implement a chunking pipeline:
  1. Receive `StorageClass::Blob` with size > threshold
  2. Split into fixed-size chunks (5 MB or 10 MB depending on total size)
  3. Encode each chunk independently (its own data+parity shards)
  4. Manifest contains a `chunks[]` array, where each chunk has its own set of shards
  5. On download: get manifest → for each chunk collect shards → decode → reassemble
- **Files**: new `chunking.rs` — `Chunker`, `Dechunker`.

#### 2.3 `network.rs` — Manifest v2

- **Current code**: Manifest contains `file_hash`, `size`, `shards: HashMap<usize, String>`.
- **What to do**: Extend Manifest:
  - `storage_class: String` — "site", "social_post", "profile", "blob"
  - `chunk_size: Option<usize>` — for blobs with chunking
  - `chunks: Option<Vec<ChunkManifest>>` — for blobs, each ChunkManifest has its own shards
  - `original_filename: Option<String>` — for blobs
  - `content_type: Option<String>` — MIME type
  - `created_at: u64` — for TTL (Phase 3)
  - `ttl_days: Option<u32>` — for GC (Phase 3)
- **Files**: `network.rs` — `Manifest` v2, `crdt.rs` — update if needed.

### Phase 2 Result

- 2 KB post generates 15 shards instead of 45 (3x less network traffic)
- 500 MB video processed in 10 MB chunks — parallel encoding/decoding
- Each storage class has optimal balance between reliability and overhead
- Manifest carries enough metadata for TTL, GC, and listing (Phases 3-4)

---

## Phase 3: Real TTL Garbage Collection + Manifest Redundancy + Proactive Healing

**Goal**: Data with TTL is actually deleted, manifest is not a single point of failure, self-healing runs constantly (not only on error).

**Expected growth**: stable storage size (doesn't grow uncontrollably), increased recovery reliability.

### What to Change

#### 3.1 New `gc.rs` — Garbage Collection

- **Current code**: TTL is not enforced. `ttl_days` exists in JSON, but no one checks it.
- **What to do**: Implement a background GC process:
  1. **Scan** (once per hour, or via cron): iterate over all locally known manifests
  2. **Check TTL**: `created_at + (ttl_days * 86400) < now()` → data expired
  3. **Delete local shards**: for each shard of the expired file — `kademlia.remove_record()`
  4. **Notify network**: send gossip message `storage_announcements` with event "expired" — other nodes also delete shards
  5. **Default policy**:
     - `Site`: **indefinite** (TTL = None)
     - `SocialPost`: **30 days**
     - `Profile`: **365 days**
     - `Blob`: **indefinite** (paid via tokenomics)
- **Files**: new `gc.rs` — `GarbageCollector` with interval loop.

#### 3.2 `swarm_loop.rs` — Manifest redundancy via Quorum

- **Current code** (line ~392): `swarm.behaviour_mut().kademlia.put_record(manifest_record, Quorum::One)` — manifest is stored on **one** node.
- **What to do**: Change to `Quorum::N` (N = 3 or more):
  - On manifest creation — publish with `Quorum::Three` (minimum 3 copies on different nodes)
  - On manifest fetch — try multiple nodes (Kademlia `get_record` automatically searches the routing table)
  - On manifest update (e.g., after self-healing) — update all copies
- **Files**: `swarm_loop.rs` — replace `Quorum::One` → `Quorum::N`, `peer_cache.rs` — use Kademlia routing table instead of JSON file.

#### 3.3 `swarm_loop.rs` — Proactive self-healing loop

- **Current code**: self-healing (`do_self_healing`) is called only when `decode_data()` returns an error — i.e., **reactively**, when data is already lost.
- **What to do**: Add a proactive cycle:
  1. **Every N hours** (e.g., 6 hours) iterate over all locally known manifests
  2. For each shard in the manifest: try `get_record` from DHT
  3. If shard is unavailable — mark as lost
  4. If lost shards > parity_shards — **do nothing** (file can be recovered)
  5. If lost ≤ parity_shards — **rebuild** lost shards via `encode_data()` and redistribute to other nodes
  6. Update manifest with new shard locations
- **Files**: `swarm_loop.rs` — `SwarmCommand::RunHealthCheck`, new loop in `run_swarm()`.

### Phase 3 Result

- Storage no longer grows uncontrollably — expired posts are deleted
- Manifest is stored on ≥3 nodes — failure tolerance
- Shards are checked proactively — data is not silently lost
- Peer cache transitions to Kademlia routing table — scalable

---

## Phase 4: Protocol Extension Layer — Foundation for Decentralized Cloud Storage

**Goal**: The storage node becomes backend-agnostic. A separate cloud storage protocol with its own SDK is layered on top. This is an **own standard** (not S3 compatibility).

**Expected growth**: the storage node transforms from "storage for sites" to "decentralized AWS" — storage of arbitrary files, listing, range requests, SDK for developers.

### Philosophy

The storage node is responsible only for **low-level byte storage**:
- Distributed storage (erasure coding + DHT)
- Recovery (self-healing)
- Time to live (TTL/GC)
- Quotas

The external protocol (separate project) is responsible for:
- **Naming**: bucket/collection name → mapping to hashes (via consensus-node)
- **Payment channels**: pay-per-byte (via tokenomics + PporTreasury)
- **ACL/access rights**: who can read/write (signatures)
- **Versioning**: file change history (immutable hashes + pointers)
- **Search/listing**: which files are in a collection, metadata, tags

### What to Change

#### 4.1 New `backends/` module — storage abstraction

- **Current code**: `swarm_loop.rs` contains hardcoded DHT storage logic. No ability to replace backend.
- **What to do**: Introduce `StorageBackend` trait:
  - `store(data: Vec<u8>, class: StorageClass) -> Result<String>` — store bytes, return hash
  - `retrieve(hash: &str) -> Result<Vec<u8>>` — get bytes by hash
  - `delete(hash: &str) -> Result<()>` — delete
  - `list_by_class(class: StorageClass, prefix: &str) -> Result<Vec<Manifest>>` — listing
- Implementations:
  - `DhtBackend` — current (shards in Kademlia DHT)
  - `DiskBackend` — for nodes with large disks (files stored locally, RS for redundancy on other nodes)
- **Files**: new `backends/mod.rs`, `backends/dht_backend.rs`, `backends/disk_backend.rs`.

#### 4.2 `main.rs` — v2 API for cloud storage

- **Current code**: HTTP handlers only for upload/download/delete by hash.
- **What to do**: Add v2 API (existing v1 handlers remain for compatibility):
  - `PUT /v2/objects/{class}/{key}` — upload object (class = site/blob/social_post/profile)
  - `GET /v2/objects/{class}/{key}` — get object
  - `HEAD /v2/objects/{class}/{key}` — get metadata only (no body)
  - `DELETE /v2/objects/{class}/{key}` — delete object
  - `GET /v2/objects/{class}?prefix=photos/2017/&limit=100` — listing objects by prefix
- **Range request support**: `Range: bytes=0-1048575` — for large files (video, archives). Especially important for streaming playback.
- **Metadata in response**: `Content-Type`, `Content-Length`, `X-Feedo-Class`, `X-Feedo-TTL`, `X-Feedo-Created-At`.
- **Files**: `main.rs` — new v2 handlers.

#### 4.3 SDK (separate project)

> SDK is not part of the storage-node, but mentioned for completeness.

```
feedo_sdk/
├── js/          # npm install @feedo/storage
├── python/      # pip install feedo-storage
├── rust/        # cargo add feedo-storage
└── dart/        # flutter pub add feedo_storage
```

Each SDK provides a simple API:
- `put_object(bucket, key, data, class="blob")` — upload
- `get_object(bucket, key)` — retrieve
- `delete_object(bucket, key)` — delete
- `list_objects(bucket, prefix)` — list
- `head_object(bucket, key)` — metadata

**This is not S3 compatibility** — it's an own standard, simpler than S3, without unnecessary HTTP baggage (no `x-amz-*` headers, no XML serialization).

### Phase 4 Result

- Storage node serves arbitrary files via a standardized API
- Listing enables "browsing folders" — like in Google Cloud
- Range requests enable video streaming without downloading the entire file
- SDK libraries enable developers to integrate in 5 minutes
- Web3 applications can use Feedo Storage as a decentralized alternative to AWS S3

---

## Phase 5: Deduplication + Streaming + Proof-of-Storage

**Goal**: Storage efficiency (deduplication), user experience quality (streaming), economic incentives for operators (proof-of-storage).

**Expected growth**: 30-50% storage volume reduction (deduplication), instant video playback (streaming), network economic stability (storage proofs).

### What to Change

#### 5.1 New `dedup.rs` — Content-Addressed Deduplication

- **Current code**: each upload creates new shards, even if the exact same file already exists in the network.
- **What to do**:
  1. Before upload: client computes `SHA256(data)` and sends the hash
  2. Storage node checks: does a manifest with this `file_hash` exist in DHT
  3. If yes — return the existing hash without re-upload (deduplication)
  4. If no — normal upload
  5. Reference counter: how many times this hash was "uploaded" by different users (for accounting)
- **Files**: new `dedup.rs` — `DeduplicationChecker`.

#### 5.2 New `streaming.rs` — Streaming upload/download

- **Current code**: upload waits for the **entire file** before starting encoding. Download waits for **all shards** before starting to serve.
- **What to do**:
  - **Upload streaming**: accept chunks via `Transfer-Encoding: chunked` → encode each chunk immediately → distribute shards without waiting for the end of file
  - **Download streaming**: as soon as the first chunk is decoded → serve to client via `Transfer-Encoding: chunked`
  - This enables: start video playback 2 seconds after request (like YouTube), instead of waiting for full download
- **Files**: new `streaming.rs`.

#### 5.3 `swarm_loop.rs` — Proof-of-Storage

- **Current code**: no mechanism to prove that a node actually stores shards. No incentives.
- **What to do**:
  1. **Challenge**: once per epoch (or on request) a node receives a random challenge — "prove you have shard X for file Y"
  2. **Proof**: node computes a Merkle proof for this shard (shard is part of file, file has Merkle root in manifest) and sends it
  3. **Verification**: consensus-node (or smart contract) verifies the proof
  4. **Reward**: successful proof → reward from PporTreasury. Failed proof → penalty (slashing)
  5. Integration with tokenomics (separate project)
- **Files**: `swarm_loop.rs` — `SwarmCommand::StorageChallenge`, integration with `accounting.rs` in consensus-node.

#### 5.4 Adaptive Replication

- **What to do**: If a file is frequently requested (hot data) → automatically increase the number of data shards (increase `DATA_SHARDS`, not `PARITY_SHARDS`). This increases availability without increasing overhead.
- **Files**: `swarm_loop.rs` — adaptive replication logic.

### Phase 5 Result

- Deduplication saves 30-50% storage (identical files stored once)
- Video streaming: playback starts in 2 seconds
- Operators receive rewards for real storage (not promises)
- Hot data automatically gets more replicas

---

## What We Will NOT Do

- ❌ **S3 compatibility** — tons of unnecessary HTTP baggage (XML, `x-amz-*`, hundreds of unused features). Own standard is simpler and faster.
- ❌ **Cold storage / archival storage** — all data is hot. The operator decides which disk to use (SSD/HDD), but from the protocol perspective — all data is equally fast.
- ❌ **Separate microservice for cloud storage** — storage-node extends, not duplicates.
- ❌ **Fixed 30+15 RS for everything** — different data classes get different parameters.
- ❌ **Ignore TTL** — expired data must be deleted.

---

## Scalability Summary Table

| Phase | Max Nodes | Volume/Node | Storage Classes | Encoding | TTL | Complexity |
|-------|-----------|-------------|-----------------|----------|-----|-----------|
| Current (baseline) | ~10-20 | 10 GB (hard limit) | None (all the same) | 30+15 for everything | Not enforced | — |
| Phase 1 (quotas + classes) ✅ | ~50-100 | ∞ (configurable) | 4 classes (Site/Social/Profile/Blob) | 30+15 for everything | Not enforced | Low (1-2 days) |
| 🔶 Tokenomics | — | — | — | — | — | Separate project |
| Phase 2 (RS + chunking) | ~100-300 | ∞ | 4 classes | Different per class + chunking | Not enforced | Medium (3-5 days) |
| Phase 3 (GC + healing) | ~300-1,000 | Stable (GC) | 4 classes | Different | ✅ Working | Medium (3-5 days) |
| Phase 4 (protocol + SDK) | ~1,000-5,000 | ∞ | 4 classes + SDK | Different | ✅ | High (1-2 weeks) |
| Phase 5 (dedup + streaming) | ~5,000-10,000+ | -30-50% (dedup) | 4 classes | Different + adaptive | ✅ | Very High (2-4 weeks) |

> **Explanation of node count**: Storage nodes scale significantly better than consensus nodes because:
> - Kademlia DHT gives O(log n) lookup complexity (not O(n²) like gossipsub)
> - No voting or consensus between storage nodes — each node independently stores shards
> - Erasure coding allows any node to hold any shard
> - Main bottleneck — Kademlia routing table size (20×log₂(n) entries) and peer discovery
> - **Key limit of Phases 1-2**: `peer_cache.json` (a single JSON file) — becomes a bottleneck at 100+ nodes
> - **After Phase 3**: transition to Kademlia routing table removes this limitation
> - **Phase 4+**: listing objects requires a local index for 5,000+ nodes

---

## Priorities by Impact

Recommended implementation order (highest impact first):

1. **Phase 1** — removes the 10 GB hard-limit, introduces storage classes. Quickest win.
2. **🔶 Tokenomics** (separate project) — economic foundation for pay-per-byte. Implemented before or in parallel with Phase 2.
3. **Phase 2** — different encoding for different data types, chunking for large files.
4. **Phase 3** — TTL starts working, manifest is no longer single point, healing is proactive.
5. **Phase 4** — decentralized cloud storage with own SDK. "AWS for Web3".
6. **Phase 5** — deduplication, streaming, economic incentives for operators.

---

## Risks and Caveats

- **Phase 1**: When introducing new fields in Manifest — old clients may not understand the new format. Backward compatibility needed (Manifest v1 → v2 with fallback).
- **Phase 2**: Chunking increases the number of shards proportionally to the number of chunks. For 500 MB video with 10 MB chunks, this is 50 chunks × 30 shards = 1,500 shards. A limit on number of chunks or parallel download is needed.
- **Phase 3**: GC must be careful — don't delete shards still needed for recovery of other files. Reference counting or cross-checking manifests is needed.
- **Phase 4**: Listing objects by prefix — this is O(n) scanning of DHT. For a large number of objects, a local index is needed (SQLite or Sled tree).
- **Phase 5**: Proof-of-Storage requires synchronization with consensus-node for verification. If consensus is under load — verification slows down.

</div>

<div id="uk">

# Storage Node — Roadmap масштабування

> **Мета**: масштабувати storage-node з поточних 10 GB/ноду до необмеженого об'єму, з різними рівнями зберігання для сайтів та файлів, і з основою для децентралізованого хмарного сховища (аналог AWS для Web3).
>
> **Актуальна проблема**: 10 GB hard-limit на ноду, однакове erasure coding для всіх типів даних (сайт 100 KB і потенційне відео 500 MB проходять через 30+15 RS), manifest без реплікації, TTL не виконується.

---

## Поточний стан (baseline)

| Параметр | Значення |
|----------|----------|
| Підтверджена кількість нод | 2 (тест `st_test.txt`) |
| Сховище | Sled (embedded key-value) |
| Ліміт | **10 GB hard-coded**, перевіряється раз на 60 сек (`main.rs` рядок 290) |
| Кодування | Reed-Solomon: 30 data + 15 parity = 45 шардів (для **всіх** типів даних) |
| Дистрибуція | Round-robin по peer'ах з `peer_cache.json` |
| Manifest | Один запис у Kademlia DHT (single point of failure) |
| Self-healing | Тільки реактивний (при невдалому decode) |
| TTL | Декларується в JSON (30 днів пости, 365 днів профілі) але **не виконується** — дані не видаляються |
| Типи даних | Все однаково — сайт, соціальний пост, профіль обробляються ідентично |
| Протокол | HTTP REST (`/upload`, `/download/:hash`, `/delete/:hash`) + gRPC + gossipsub pub/sub + WebSocket |
| Мертвий код | `old_main_p2p.rs` |

### Ключові архітектурні проблеми

1. **10 GB hard-limit**: нода просто перестає приймати дані після досягнення ліміту. Немає graceful degradation, немає квот для різних типів даних.
2. **Однакове Erasure Coding для всього**: 30+15 (45 шардів, 50% overhead) застосовується і до JSON-поста розміром 2 KB, і до потенційного відеофайлу 500 MB. Для великих файлів це створює зайвий мережевий overhead без потреби.
3. **Manifest у DHT без реплікації**: один запис на одній ноді. Якщо ця нода офлайн — файл неможливо відновити, навіть якщо всі шарди доступні.
4. **Немає TTL garbage collection**: поле `ttl_days` передається в JSON при ingest, але жоден код не видаляє прострочені дані. Сховище росте безконтрольно.
5. **Немає інтерфейсу для зовнішнього протоколу**: усе захардкожено в HTTP ручках. Неможливо нашарувати окремий протокол хмарного сховища без зміни ядра.
6. **Peer cache у JSON-файлі**: не масштабується на сотні нод. Kademlia routing table уже є в libp2p, але не використовується для цієї цілі.

---

## Фаза 1: Гнучкі квоти + Storage Classes ✅ DONE (2026-07-11)

**Ціль**: Прибрати 10 GB hard-limit, ввести роздільні квоти для різних типів даних, закласти основу для майбутнього хмарного протоколу.

**Очікуваний приріст**: об'єм/ноду стає конфігурованим (∞ з операторськими квотами), з'являється поділ на storage classes.

### Що змінити

#### 1.1 `main.rs` — заміна `storage_full` на `StorageQuotaManager`

- **Поточний код** (лінії ~286-297): кожні 60 секунд перевіряє `get_dir_size()`, якщо > 10 GB — встановлює `storage_full = true`. Після цього нода припиняє приймати будь-які дані.
- **Що зробити**: Замінити на `StorageQuotaManager` з окремими квотами:
  - `QUOTA_SITES_GB` — сайти (найвищий пріоритет, безстрокове зберігання)
  - `QUOTA_BLOBS_GB` — файли/хмарне сховище (окрема квота, платна)
  - `QUOTA_SOCIAL_MB` — пости (найнижчий пріоритет, тимчасові)
  - `QUOTA_PROFILES_MB` — профілі (середній пріоритет)
- При досягненні квоти для конкретного класу — **не reject**, а backpressure (лог Warn, метрика для оператора, сповільнення прийому).
- Оператор ноди сам вирішує: 100 GB під сайти, 1 TB під файли, 500 MB під пости.
- **Файли**: `main.rs` — заміна логіки, новий `quota.rs` — `StorageQuotaManager`.

#### 1.2 `main.rs` + `swarm_loop.rs` — введення `StorageClass`

- **Поточний код**: всі дані обробляються однаково. Немає поля, що розрізняє тип даних.
- **Що зробити**: Додати enum `StorageClass`:
  - `Site` — HTML/CSS/JS сайти (завантажуються через `/upload` або `proxy_publish_feedo`)
  - `SocialPost` — Nostr-пости (через `/api/v1/ingest/post`)
  - `Profile` — Nostr-профілі (через `/api/v1/ingest/batch`)
  - `Blob` — довільні файли (основа для майбутнього хмарного протоколу)
- Клієнт передає `storage_class` при upload (HTTP header `X-Feedo-Storage-Class` або поле в JSON-тілі).
- `IngestPayload` (рядок 123 `main.rs`) отримує поле `storage_class`.
- Manifest отримує поле `storage_class`.
- **Файли**: `main.rs` — `StorageClass` enum + розширення `IngestPayload`, `network.rs` — Manifest v2.

### Результат фази 1

- Оператор контролює скільки місця виділити під сайти vs файли
- Нода не "вмирає" при досягненні ліміту — тільки сповільнює прийом для переповненого класу
- Storage classes готові для Фази 2 (різне кодування)
- Пости можуть бути обмежені 500 MB і автоматично видалятися (Фаза 3), не займаючи місце для сайтів

---

## 🔶 Токеноміка (окремий проект)

> **Розташування**: між Фазою 1 та Фазою 2. Детально продумана, реалізується як окремий файл/проект.

**Роль у storage roadmap**: визначає економічну модель pay-per-byte через `PporTreasury.sol` (уже існує). Користувач депонує USDC на Polygon → отримує квоту на X GB/місяць. Оператори нод отримують винагороду за зберігання + трафік.

**Вплив на storage-node**:
- Фаза 2+ використовує баланс користувача для визначення `storage_class=Blob` квоти
- `StorageQuotaManager` враховує не тільки локальні квоти, а й глобальний баланс через gRPC до consensus-node
- Proof-of-Storage (Фаза 5) інтегрується з винагородами з treasury

> **Примітка**: токеноміка не є частиною цього roadmap — це окремий документ. Тут вона згадується лише як зовнішня залежність.

---

## Фаза 2: Параметризоване Erasure Coding + Chunking для великих файлів

**Ціль**: Різні параметри кодування для різних storage classes, підтримка файлів будь-якого розміру через chunking.

**Очікуваний приріст**: ефективне використання мережі (менше шардів для малих даних), підтримка файлів >100 MB без деградації.

### Що змінити

#### 2.1 `swarm_loop.rs` — параметризація Reed-Solomon за `StorageClass`

- **Поточний код**: константи `DATA_SHARDS = 30`, `PARITY_SHARDS = 15`, `TOTAL_SHARDS = 45` використовуються для всіх даних.
- **Що зробити**: Замінити константи на функцію `get_rs_params(class: StorageClass, file_size: usize) -> (usize, usize)`:
  - `Site` (безстрокове, висока важливість): **30+15** (45 шардів, overhead 50%, витримує втрату 15 нод)
  - `SocialPost` (тимчасове, низька важливість): **10+5** (15 шардів, overhead 50%, витримує втрату 5 нод)
  - `Profile` (середня важливість, легко перестворити): **5+3** (8 шардів, overhead 60%)
  - `Blob` ≤10 MB: **20+10** (30 шардів, надійне зберігання файлів)
  - `Blob` 10-100 MB: chunk по 5 MB, кожен чанк **15+7** (22 шарди)
  - `Blob` >100 MB: chunk по 10 MB, кожен чанк **20+10** (30 шардів)
- **Файли**: `swarm_loop.rs` — заміна констант на функцію, `network.rs` — константи перенести або видалити.

#### 2.2 Новий `chunking.rs` — розбиття великих файлів на чанки

- **Поточний код**: весь файл кодується як один блок. Для 500 MB відео це 500 MB у пам'яті + 45 шардів.
- **Що зробити**: Реалізувати chunking pipeline:
  1. Отримати `StorageClass::Blob` з розміром > threshold
  2. Розбити на чанки фіксованого розміру (5 MB або 10 MB залежно від загального розміру)
  3. Кожен чанк кодується незалежно (свої data+parity шарди)
  4. Manifest містить масив `chunks[]`, де кожен чанк має свій набір шардів
  5. При скачуванні: отримати manifest → для кожного чанка зібрати шарди → декодувати → об'єднати
- **Файли**: новий `chunking.rs` — `Chunker`, `Dechunker`.

#### 2.3 `network.rs` — Manifest v2

- **Поточний код**: Manifest містить `file_hash`, `size`, `shards: HashMap<usize, String>`.
- **Що зробити**: Розширити Manifest:
  - `storage_class: String` — "site", "social_post", "profile", "blob"
  - `chunk_size: Option<usize>` — для blob-ів з chunking
  - `chunks: Option<Vec<ChunkManifest>>` — для blob-ів, кожен ChunkManifest має свої shards
  - `original_filename: Option<String>` — для blob-ів
  - `content_type: Option<String>` — MIME type
  - `created_at: u64` — для TTL (Фаза 3)
  - `ttl_days: Option<u32>` — для GC (Фаза 3)
- **Файли**: `network.rs` — `Manifest` v2, `crdt.rs` — оновлення за потреби.

### Результат фази 2

- Пост 2 KB генерує 15 шардів замість 45 (у 3 рази менше мережевого трафіку)
- Відео 500 MB обробляється чанками по 10 MB — паралельне кодування/декодування
- Кожен storage class має оптимальний баланс між надійністю та overhead
- Manifest несе достатньо метаданих для TTL, GC, і listing (Фази 3-4)

---

## Фаза 3: Справжній TTL Garbage Collection + Manifest Redundancy + Proactive Healing

**Ціль**: Дані з TTL реально видаляються, manifest не є single point of failure, self-healing працює постійно (не тільки при помилці).

**Очікуваний приріст**: стабільний розмір сховища (не росте безконтрольно), підвищена надійність відновлення.

### Що змінити

#### 3.1 Новий `gc.rs` — Garbage Collection

- **Поточний код**: TTL не виконується. `ttl_days` лежить в JSON, але ніхто його не перевіряє.
- **Що зробити**: Реалізувати фоновий GC-процес:
  1. **Сканування** (раз на годину, або за кроном): пройтися по всіх локально відомих manifest'ах
  2. **Перевірка TTL**: `created_at + (ttl_days * 86400) < now()` → дані прострочені
  3. **Видалення локальних шардів**: для кожного шарда простроченого файлу — `kademlia.remove_record()`
  4. **Сповіщення мережі**: відправити gossip-повідомлення `storage_announcements` з подією "expired" — інші ноди теж видаляють шарди
  5. **Політика за замовчуванням**:
     - `Site`: **безстроково** (TTL = None)
     - `SocialPost`: **30 днів**
     - `Profile`: **365 днів**
     - `Blob`: **безстроково** (оплачено через токеноміку)
- **Файли**: новий `gc.rs` — `GarbageCollector` з інтервальним циклом.

#### 3.2 `swarm_loop.rs` — Manifest redundancy через Quorum

- **Поточний код** (лінія ~392): `swarm.behaviour_mut().kademlia.put_record(manifest_record, Quorum::One)` — manifest зберігається на **одній** ноді.
- **Що зробити**: Змінити на `Quorum::N` (N = 3 або більше):
  - При створенні manifest'у — публікувати з `Quorum::Three` (мінімум 3 копії на різних нодах)
  - При fetch manifest'у — пробувати кілька нод (Kademlia `get_record` автоматично шукає по routing table)
  - При оновленні manifest'у (наприклад, після self-healing) — оновлювати всі копії
- **Файли**: `swarm_loop.rs` — заміна `Quorum::One` → `Quorum::N`, `peer_cache.rs` — використання Kademlia routing table замість JSON-файлу.

#### 3.3 `swarm_loop.rs` — Proactive self-healing loop

- **Поточний код**: self-healing (`do_self_healing`) викликається тільки коли `decode_data()` повертає помилку — тобто **реактивно**, коли дані вже втрачено.
- **Що зробити**: Додати proactive цикл:
  1. **Раз на N годин** (наприклад, 6 год) обійти всі локально відомі manifest'и
  2. Для кожного шарда в manifest'і: спробувати `get_record` з DHT
  3. Якщо шард недоступний — позначити як втрачений
  4. Якщо втрачених шардів > parity_shards — **нічого не робити** (файл можна відновити)
  5. Якщо втрачених ≤ parity_shards — **перебудувати** втрачені шарди через `encode_data()` і перерозподілити на інші ноди
  6. Оновити manifest з новими розташуваннями шардів
- **Файли**: `swarm_loop.rs` — `SwarmCommand::RunHealthCheck`, новий цикл у `run_swarm()`.

### Результат фази 3

- Сховище більше не росте безконтрольно — прострочені пости видаляються
- Manifest зберігається на ≥3 нодах — стійкість до відмов
- Шарди перевіряються проактивно — дані не губляться мовчки
- Peer cache переходить на Kademlia routing table — масштабується

---

## Фаза 4: Protocol Extension Layer — основа для децентралізованого хмарного сховища

**Ціль**: Storage-нода стає backend-агностиком. На неї нашаровується окремий протокол хмарного сховища з власним SDK. Це **власний стандарт** (не S3-сумісність).

**Очікуваний приріст**: storage-node перетворюється з "сховища для сайтів" на "децентралізований AWS" — зберігання довільних файлів, listing, range requests, SDK для розробників.

### Філософія

Storage-нода відповідає тільки за **низькорівневе зберігання байтів**:
- Розподілене зберігання (erasure coding + DHT)
- Відновлення (self-healing)
- Час життя (TTL/GC)
- Квоти

Зовнішній протокол (окремий проект) відповідає за:
- **Неймінг**: назва бакету/колекції → mapping до hash'ів (через consensus-node)
- **Платіжні канали**: pay-per-byte (через токеноміку + PporTreasury)
- **ACL/права доступу**: хто може читати/писати (підписи)
- **Версіонування**: історія змін файлу (immutable hash'і + pointers)
- **Пошук/listing**: які файли є в колекції, метадані, теги

### Що змінити

#### 4.1 Новий `backends/` модуль — абстракція сховища

- **Поточний код**: `swarm_loop.rs` містить hardcoded логіку DHT-зберігання. Немає можливості замінити backend.
- **Що зробити**: Ввести trait `StorageBackend`:
  - `store(data: Vec<u8>, class: StorageClass) -> Result<String>` — зберегти байти, повернути hash
  - `retrieve(hash: &str) -> Result<Vec<u8>>` — отримати байти за hash
  - `delete(hash: &str) -> Result<()>` — видалити
  - `list_by_class(class: StorageClass, prefix: &str) -> Result<Vec<Manifest>>` — listing
- Реалізації:
  - `DhtBackend` — поточний (шарди в Kademlia DHT)
  - `DiskBackend` — для нод з великими дисками (файли зберігаються локально, RS — для redundancy на інших нодах)
- **Файли**: новий `backends/mod.rs`, `backends/dht_backend.rs`, `backends/disk_backend.rs`.

#### 4.2 `main.rs` — v2 API для хмарного сховища

- **Поточний код**: HTTP ручки тільки для upload/download/delete за hash.
- **Що зробити**: Додати v2 API (існуючі ручки v1 залишаються для сумісності):
  - `PUT /v2/objects/{class}/{key}` — завантажити об'єкт (class = site/blob/social_post/profile)
  - `GET /v2/objects/{class}/{key}` — отримати об'єкт
  - `HEAD /v2/objects/{class}/{key}` — отримати тільки метадані (без тіла)
  - `DELETE /v2/objects/{class}/{key}` — видалити об'єкт
  - `GET /v2/objects/{class}?prefix=photos/2017/&limit=100` — listing об'єктів за префіксом
- **Підтримка Range requests**: `Range: bytes=0-1048575` — для великих файлів (відео, архіви). Особливо важливо для streaming-відтворення.
- **Метадані у відповіді**: `Content-Type`, `Content-Length`, `X-Feedo-Class`, `X-Feedo-TTL`, `X-Feedo-Created-At`.
- **Файли**: `main.rs` — нові ручки v2.

#### 4.3 SDK (окремий проект)

> SDK не є частиною storage-node, але згадується для повноти картини.

```
feedo_sdk/
├── js/          # npm install @feedo/storage
├── python/      # pip install feedo-storage
├── rust/        # cargo add feedo-storage
└── dart/        # flutter pub add feedo_storage
```

Кожен SDK надає простий API:
- `put_object(bucket, key, data, class="blob")` — завантажити
- `get_object(bucket, key)` — отримати
- `delete_object(bucket, key)` — видалити
- `list_objects(bucket, prefix)` — список
- `head_object(bucket, key)` — метадані

**Це не S3-сумісність** — це власний стандарт, простіший за S3, без зайвого HTTP-багажу (жодних `x-amz-*` хедерів, жодної XML-серіалізації).

### Результат фази 4

- Storage-нода обслуговує довільні файли через стандартизований API
- Listing дозволяє "переглядати папки" — як у Google Cloud
- Range requests дозволяють стрімити відео без завантаження всього файлу
- SDK-бібліотеки дозволяють розробникам інтегруватися за 5 хвилин
- Web3-додатки можуть використовувати Feedo Storage як децентралізовану альтернативу AWS S3

---

## Фаза 5: Дедуплікація + Стримінг + Proof-of-Storage

**Ціль**: Ефективність використання сховища (дедуплікація), якість користувацького досвіду (стримінг), економічні стимули для операторів (proof-of-storage).

**Очікуваний приріст**: зменшення об'єму сховища на 30-50% (дедуплікація), миттєве відтворення відео (стримінг), економічна стійкість мережі (докази зберігання).

### Що змінити

#### 5.1 Новий `dedup.rs` — Content-Addressed дедуплікація

- **Поточний код**: кожен upload створює нові шарди, навіть якщо точно такий самий файл уже є в мережі.
- **Що зробити**:
  1. Перед завантаженням: клієнт обчислює `SHA256(data)` і відправляє hash
  2. Storage-нода перевіряє: чи є manifest з таким `file_hash` у DHT
  3. Якщо є — повертає існуючий hash без повторного завантаження (дедуплікація)
  4. Якщо немає — звичайний upload
  5. Лічильник посилань: скільки разів цей hash був "завантажений" різними користувачами (для обліку)
- **Файли**: новий `dedup.rs` — `DeduplicationChecker`.

#### 5.2 Новий `streaming.rs` — Streaming upload/download

- **Поточний код**: upload чекає **весь файл** перед початком кодування. Download чекає **всі шарди** перед початком віддачі.
- **Що зробити**:
  - **Upload streaming**: приймати чанки через `Transfer-Encoding: chunked` → кодувати кожен чанк одразу → розподіляти шарди, не чекаючи кінця файлу
  - **Download streaming**: як тільки перший чанк декодовано → віддавати клієнту через `Transfer-Encoding: chunked`
  - Це дозволяє: почати відтворення відео через 2 секунди після запиту (як YouTube), а не чекати повного завантаження
- **Файли**: новий `streaming.rs`.

#### 5.3 `swarm_loop.rs` — Proof-of-Storage

- **Поточний код**: немає механізму доказу, що нода дійсно зберігає шарди. Немає стимулів.
- **Що зробити**:
  1. **Challenge**: раз на епоху (або за запитом) нода отримує випадковий challenge — "доведи що в тебе є шард X для файлу Y"
  2. **Proof**: нода обчислює Merkle proof для цього шарду (шард є частиною файлу, файл має Merkle root у manifest) і відправляє
  3. **Verification**: consensus-node (або смарт-контракт) верифікує proof
  4. **Reward**: успішний proof → винагорода з PporTreasury. Провалений proof → штраф (slashing)
  5. Інтеграція з токеномікою (окремий проект)
- **Файли**: `swarm_loop.rs` — `SwarmCommand::StorageChallenge`, інтеграція з `accounting.rs` у consensus-node.

#### 5.4 Адаптивна реплікація

- **Що зробити**: Якщо файл часто запитують (гарячі дані) → автоматично збільшити кількість data-шардів (підвищити `DATA_SHARDS`, не `PARITY_SHARDS`). Це збільшує доступність без збільшення overhead.
- **Файли**: `swarm_loop.rs` — логіка адаптивної реплікації.

### Результат фази 5

- Дедуплікація економить 30-50% сховища (однакові файли зберігаються один раз)
- Стримінг відео: перегляд починається через 2 секунди
- Оператори отримують винагороду за реальне зберігання (не за обіцянки)
- Гарячі дані автоматично отримують більше реплік

---

## Що НЕ будемо робити

- ❌ **S3-сумісність** — купа непотрібного HTTP-багажу (XML, `x-amz-*`, сотні невикористовуваних фіч). Власний стандарт простіший і швидший.
- ❌ **Cold storage / архівне сховище** — всі дані гарячі. Оператор сам вирішує який диск використовувати (SSD/HDD), але з точки зору протоколу — всі дані доступні однаково швидко.
- ❌ **Окремий мікросервіс для хмарного сховища** — storage-node розширюється, а не дублюється.
- ❌ **Фіксоване 30+15 RS для всього** — різні класи даних отримують різні параметри.
- ❌ **Ігнорувати TTL** — дані, що прострочилися, мають видалятися.

---

## Підсумкова таблиця масштабованості

| Фаза | Макс. нод | Об'єм/ноду | Storage Classes | Кодування | TTL | Складність |
|------|-----------|-----------|-----------------|-----------|-----|-----------|
| Зараз (baseline) | ~10-20 | 10 GB (hard limit) | Немає (все однаково) | 30+15 для всього | Не виконується | — |
| Фаза 1 (квоти + класи) ✅ | ~50-100 | ∞ (конфігуровано) | 4 класи (Site/Social/Profile/Blob) | 30+15 для всього | Не виконується | Низька (1-2 дні) |
| 🔶 Токеноміка | — | — | — | — | — | Окремий проект |
| Фаза 2 (RS + chunking) | ~100-300 | ∞ | 4 класи | Різне для різних + chunking | Не виконується | Середня (3-5 днів) |
| Фаза 3 (GC + healing) | ~300-1,000 | Стабільний (GC) | 4 класи | Різне | ✅ Працює | Середня (3-5 днів) |
| Фаза 4 (протокол + SDK) | ~1,000-5,000 | ∞ | 4 класи + SDK | Різне | ✅ | Висока (1-2 тижні) |
| Фаза 5 (дедуп + стримінг) | ~5,000-10,000+ | -30-50% (дедуп) | 4 класи | Різне + адаптивне | ✅ | Дуже висока (2-4 тижні) |

> **Пояснення щодо кількості нод**: Storage-ноди масштабуються значно краще за consensus-ноди, тому що:
> - Kademlia DHT дає O(log n) складність пошуку (не O(n²) як gossipsub)
> - Немає голосування чи консенсусу між storage-нодами — кожна нода незалежно зберігає шарди
> - Erasure coding дозволяє будь-якій ноді тримати будь-який шард
> - Основний bottleneck — розмір routing table Kademlia (20×log₂(n) записів) і peer discovery
> - **Ключовий ліміт Фази 1-2**: `peer_cache.json` (один JSON-файл) — стає вузьким місцем при 100+ нодах
> - **Після Фази 3**: перехід на Kademlia routing table знімає це обмеження
> - **Фаза 4+**: listing об'єктів потребує локального індексу для 5,000+ нод

---

## Пріоритети за впливом

Рекомендований порядок впровадження (найбільший impact першим):

1. **Фаза 1** — прибирає 10 GB hard-limit, вводить storage classes. Найшвидша перемога.
2. **🔶 Токеноміка** (окремий проект) — економічна основа для pay-per-byte. Впроваджується до або паралельно з Фазою 2.
3. **Фаза 2** — різне кодування для різних типів даних, chunking для великих файлів.
4. **Фаза 3** — TTL починає працювати, manifest перестає бути single point, healing проактивний.
5. **Фаза 4** — децентралізоване хмарне сховище з власним SDK. "AWS для Web3".
6. **Фаза 5** — дедуплікація, стримінг, економічні стимули для операторів.

---

## Ризики та застереження

- **Фаза 1**: При введенні нових полів у Manifest — старі клієнти можуть не розуміти новий формат. Потрібна backward compatibility (Manifest v1 → v2 з fallback).
- **Фаза 2**: Chunking збільшує кількість шардів пропорційно до кількості чанків. Для 500 MB відео з chunk по 10 MB це 50 чанків × 30 шардів = 1500 шардів. Потрібен ліміт на кількість чанків або паралельне завантаження.
- **Фаза 3**: GC повинен бути обережним — не видаляти шарди, які ще потрібні для recovery інших файлів. Потрібен reference counting або перехресна перевірка manifest'ів.
- **Фаза 4**: Listing об'єктів за префіксом — це O(n) сканування DHT. Для великої кількості об'єктів потрібен локальний індекс (SQLite або Sled tree).
- **Фаза 5**: Proof-of-Storage потребує синхронізації з consensus-node для верифікації. Якщо consensus під навантаженням — верифікація сповільнюється.

</div>