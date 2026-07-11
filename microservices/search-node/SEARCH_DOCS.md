# Search Node — Technical Documentation

> **Version**: 0.2.0 (Phase 1 + 1.5 complete)
> **Language**: Python 3 (FastAPI + uvicorn)
> **Last updated**: 2026-07-11

---

## 1. Overview

The **search-node** is a decentralised vector search microservice in the Feedo ecosystem. It indexes text and image embeddings in a local **LanceDB** vector database, uses **KMeans centroids** for semantic sharding and federated search, and participates in a P2P network where each node stores only its assigned semantic shard.

### Key capabilities

| Capability | Description |
|------------|-------------|
| **Vector Search** | Cosine distance search over 384-dim text embeddings (`multilingual-e5-small`) and 512-dim image embeddings (`CLIP`). |
| **Semantic Sharding** | KMeans centroids partition the embedding space into N shards. Each node stores only ~1/N of the global index. |
| **Federated Search** | Queries are routed to the top-K peers whose centroids are closest to the query vector. Results are merged and deduplicated. |
| **P2P Centroid Handshake** | Nodes periodically broadcast their local KMeans centroids to all known peers. Event-driven updates trigger on significant centroid drift. |
| **Multi-modal** | CLIP model supports image embeddings alongside text. Queries can match both modalities. |
| **Rate Limiting** | Token-bucket rate limiter per endpoint (100 req/s query, 50 req/s index, 200 req/s P2P). |
| **Batch Crawler** | WebSocket PubSub subscriber with batch embedding (32 events / 1 sec) for high-throughput indexing. |
| **Multi-language** | `langdetect` for automatic language detection during indexing. |

### High-level architecture

```
┌──────────────────────────────────────────────────────────┐
│                    External Clients                       │
│         HTTP (FastAPI)         WebSocket (PubSub)         │
└──────────────┬──────────────────┬────────────────────────┘
               │                  │
┌──────────────▼──────────────────▼────────────────────────┐
│                      main.py                              │
│  Global: brain, p2p_net, crawler, GATEWAYS               │
│  • /query, /documents, /index_document                    │
│  • /p2p/handshake, /p2p/search, /p2p/index_vector        │
│  • /proxy/publish, /proxy/unpin                           │
│  • /explorer/stats, /v1/node/peers                        │
│  • TokenBucketRateLimiter (middleware)                    │
└──────────┬──────────────┬──────────────┬─────────────────┘
           │              │              │
┌──────────▼──────┐ ┌─────▼──────┐ ┌────▼──────────────┐
│ vector_service  │ │  crawler   │ │       p2p          │
│     .py         │ │    .py     │ │       .py          │
│                 │ │            │ │                    │
│ VectorBrain     │ │SearchCrawler│ │  P2PNetwork       │
│ • Embeddings    │ │ • PubSub   │ │ • Centroid handshake│
│ • LanceDB       │ │ • Batch    │ │ • Federated search │
│ • KMeans        │ │ • Write    │ │ • Event-driven    │
│ • Global Map    │ │   routing  │ │   updates         │
│ • Sharding      │ │            │ │                    │
└─────────────────┘ └────────────┘ └────────────────────┘
```

---

## 2. Architecture

### 2.1 Protocol stack

```
┌──────────────────────────────────┐
│  HTTP REST (FastAPI 0.110)        │   ← Application layer
├──────────────────────────────────┤
│  sentence-transformers (2.5)      │   ← ML inference
│  ├─ intfloat/multilingual-e5-small│   (384-dim text)
│  └─ clip-ViT-B-32                │   (512-dim image)
├──────────────────────────────────┤
│  LanceDB (0.5)                    │   ← Vector database
│  scikit-learn (1.4)               │   ← KMeans + NearestNeighbors
│  numpy (1.26)                     │   ← Linear algebra
├──────────────────────────────────┤
│  httpx (0.27) + aiohttp (3.9)     │   ← HTTP clients
│  websockets (12.0)               │   ← PubSub crawler
│  grpcio (1.62)                   │   ← Consensus-node gRPC
├──────────────────────────────────┤
│  langdetect (1.0)                 │   ← Language detection
│  Pillow (10.2)                    │   ← Image loading (CLIP)
│  onnxruntime (1.17)               │   ← (future) GPU inference
└──────────────────────────────────┘
```

### 2.2 Data flow: Vector Indexing with Semantic Sharding (Phase 1.5)

```
Storage Node (PubSub WebSocket)
  │ 1. New content event published to "feedo_new_events" topic
  ▼
crawler.py: crawl_loop()
  │ 2. Accumulate events in batch buffer (32 events or 1 second)
  │ 3. Flush → _flush_batch()
  ▼
vector_service.py: get_embeddings_batch_async(texts)
  │ 4. Batch encode all texts → N × 384-dim vectors
  ▼
vector_service.py: is_my_shard(vector) for each vector
  │ 5a. YES → add_vector_by_emb() → LanceDB (local index)
  │ 5b. NO  → route_vector_to_node(vector) → target_url
  │               │
  │               ▼
  │          crawler.py: _forward_vector_to_peer(target_url, event, vector)
  │               │  POST /p2p/index_vector
  │               ▼
  │          Remote search-node: main.py → p2p_index_vector()
  │               │  add_vector_by_emb() → LanceDB (remote index)
  │               ▼
  │          {"status": "ok"} (or fallback to local if unreachable)
```

**Key decision point — `is_my_shard(vector)`:**
1. Get my local KMeans centroids (cached, recomputed every 100 vectors or 10 minutes)
2. Compute `my_min_similarity` — max cosine similarity from vector to any of my centroids
3. Get foreign centroids from `global_knowledge_map` (built from peer handshakes)
4. If no foreign centroids → `True` (fallback: solo node indexes everything)
5. Compute `foreign_min_similarity` — max cosine similarity to any foreign centroid
6. Return `my_min_similarity >= foreign_min_similarity`

### 2.3 Data flow: Federated Search

```
Client
  │ GET /query?text=...&limit=50&federated=true
  ▼
main.py: client_query()
  │ 1. brain.get_embedding_async(text, is_query=True) → query_vector (384-dim)
  ▼
Local search:
  │ 2. LanceDB table.search(query_vector).limit(limit*5).to_list()
  │    → local_results (sorted by cosine distance)
  ▼
vector_service.py: route_query(query_vector, top_k=5)
  │ 3. NearestNeighbors search over global_knowledge_map centroids
  │    → target_peers (top-5 peer URLs whose centroids are closest)
  ▼
p2p.py: federated_search(query_vector, text, ttl=3, top_k=5)
  │ 4. POST /p2p/search to each target_peer
  │    asyncio.wait_for(asyncio.gather(...), timeout=2.0)
  │    → federated_results
  ▼
Merge & Deduplicate:
  │ 5. all_results = local_results + federated_results
  │ 6. Sort by score descending
  │ 7. Group by hash_id: first occurrence = primary, duplicates added to "duplicates" list
  │ 8. Promote richer metadata if duplicate has more fields
  ▼
Return:
  │ 9. {"results": [...]} — offset/limit applied, missing text fetched from DHT
```

### 2.4 Module map

| File | Lines | Role |
|------|-------|------|
| `main.py` | ~500 | Entry point: FastAPI server, 13 endpoints, rate limiter middleware, startup lifecycle |
| `vector_service.py` | ~570 | Core: VectorBrain class — embeddings, LanceDB CRUD, KMeans centroids, global knowledge map, semantic sharding logic, caching |
| `crawler.py` | ~165 | PubSub subscriber: WebSocket batch processing, semantic sharding write routing, peer forwarding |
| `p2p.py` | ~160 | P2P networking: centroid handshake broadcast (periodic + event-driven), federated search aggregation |
| `storage_adapters.py` | ~80 | Storage abstraction layer: FeedoStorageAdapter (HTTP to storage-node), IPFSStorageAdapter |

---

## 3. Module Reference

### 3.1 `main.py` — Entry Point

**Global state:**

```python
# Initialised at module load
brain = VectorBrain(db_path=lance_db_path)     # LanceDB + ML models + centroids
p2p_net = None                                   # P2PNetwork (initialised in startup)
crawler = None                                   # SearchCrawler (initialised in startup)
GATEWAYS = [...]                                 # Storage node URLs from env
```

**Startup flow** (`on_event("startup")`):
1. Create `P2PNetwork(brain, host, port)` — reads `KNOWN_PEERS`, `PUBLIC_API_URL`
2. Spawn background task: `p2p_net.broadcast_centroids_loop()`
3. Create shared `httpx.AsyncClient` with timeout from `SHARD_FORWARD_TIMEOUT` (default 5s)
4. Create `SearchCrawler(brain, adapters, http_client)`
5. Spawn background task: `crawler.crawl_loop()`

**TokenBucketRateLimiter:**

| Path | Rate (req/s) | Capacity |
|------|-------------|----------|
| `/query` | 100 | 100 |
| `/index_document` | 50 | 50 |
| `/p2p/search` | 200 | 200 |
| `/p2p/index_vector` | 200 | 200 |

Algorithm: token bucket with per-path buckets. Tokens refill at `rate` per second up to `capacity`. If insufficient tokens for 1.0, returns HTTP 429.

**Pydantic models:**

```python
class HandshakePayload(BaseModel):
    peer_id: str
    centroids: list[list[float]]       # K × 384-dim centroids
    cluster_ids: list[str]             # K cluster labels

class SearchPayload(BaseModel):
    query: str
    ttl: int = 3                        # Decremented per hop

class IndexDocumentPayload(BaseModel):
    hash_id: str
    author: str = ""
    text: str = ""
    item_type: str = "document"
    metadata: dict = {}

class IndexVectorPayload(BaseModel):
    """Phase 1.5: Receive pre-computed vector from peer."""
    post_id: int
    hash_id: str
    vector: list[float]                 # 384-dim
    text: str = ""
    source_type: str = "pubsub"
    item_type: str = "text"
    author: str = ""
    metadata: str = ""
```

**HTTP API routes:**

| Method | Route | Handler | Description |
|--------|-------|---------|-------------|
| GET | `/query` | `client_query` | Vector search with optional federation |
| GET | `/documents` | `get_documents` | Latest indexed documents |
| POST | `/index_document` | `index_document` | Manual document indexing |
| POST | `/p2p/handshake` | `p2p_handshake` | Receive centroids from peer |
| POST | `/p2p/search` | `p2p_search` | Federated search query |
| POST | `/p2p/index_vector` | `p2p_index_vector` | Receive vector for local indexing (Phase 1.5) |
| GET | `/explorer/stats` | `get_explorer_stats` | Node statistics |
| GET | `/v1/node/peers` | `get_peers` | Known peers list |
| POST | `/proxy/publish` | `proxy_publish` | Publish site via Pinata |
| POST | `/proxy/publish_feedo` | `proxy_publish_feedo` | Publish site via storage-node |
| DELETE | `/proxy/unpin/{cid}` | `proxy_unpin` | Delete from Pinata + index |
| DELETE | `/proxy/unpin_feedo/{cid}` | `proxy_unpin_feedo` | Delete from storage-node + index |

### 3.2 `vector_service.py` — Vector Brain

**Class:** `VectorBrain` — the central module containing all embedding, storage, clustering, and routing logic.

**Key fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `model` | `SentenceTransformer` | Text embedding model (`multilingual-e5-small`, 384-dim) |
| `image_model` | `SentenceTransformer` | Image embedding model (`clip-ViT-B-32`, 512-dim) |
| `db` | `lancedb.DBConnection` | LanceDB connection |
| `table` | `lancedb.table.Table` | LanceDB table (`post_vectors`) |
| `executor` | `ThreadPoolExecutor` | CPU-bound inference pool (`os.cpu_count()` workers) |
| `emb_cache` | `OrderedDict` | LRU embedding cache (100K entries, TTL 1 hour) |
| `search_cache` | `dict` | Search result cache (20K entries, TTL 5 minutes) |
| `global_knowledge_map` | `list[dict]` | Foreign centroids: `[{centroid, peer_id, cluster_id}]` |
| `nn_model` | `NearestNeighbors` | ANN model fitted on global_knowledge_map for fast routing |
| `nn_fitted` | `bool` | Whether nn_model has been fitted |

**Phase 1.5 sharding fields:**

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `_my_centroids_cache` | `list[list[float]] \| None` | `None` | Cached local KMeans centroids |
| `_my_centroids_ts` | `float` | `0.0` | Timestamp of last centroid computation |
| `_centroids_cache_ttl` | `int` | `600` | Cache TTL in seconds |
| `inserts_since_centroids_update` | `int` | `0` | Counter for cache invalidation |
| `_centroids_update_threshold` | `int` | `100` | Vectors before cache reset |
| `_sharding_enabled` | `bool` | `true` | Feature flag: `SEMANTIC_SHARDING_ENABLED` |

**LanceDB schema** (`post_vectors` table):

| Column | Type | Description |
|--------|------|-------------|
| `post_id` | `int32` | Random post identifier |
| `hash_id` | `string` | Content-addressed hash (SHA256) |
| `vector` | `list<float32>(384)` | Text embedding |
| `image_vector` | `list<float32>(512)` | Image embedding (CLIP) |
| `timestamp` | `float64` | Unix timestamp of indexing |
| `source_type` | `string` | Origin: `"pubsub"`, `"native"` |
| `item_type` | `string` | Content type: `"text"`, `"website"`, `"document"` |
| `language` | `string` | Detected language code (`langdetect`) |
| `geo` | `string` | Geographic tag (reserved) |
| `relay_url` | `string` | Relay URL (reserved) |
| `author` | `string` | Author DID |
| `text` | `string` | Full text content |
| `metadata` | `string` | JSON-encoded metadata |

**Embedding methods:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_embedding()` | `(text, is_query=False) → list[float]` | Single text → 384-dim vector. Prefixes with `"query: "` or `"passage: "`. |
| `get_embeddings_batch()` | `(texts, batch_size=32) → list[list[list[float]]]` | Batch encode with chunking. Each text can produce multiple chunk vectors. |
| `get_image_embedding()` | `(image_url) → list[float]` | Download image → CLIP → 512-dim vector. |
| `chunk_text()` | `(text, max_words=350) → list[str]` | Splits long text into overlapping chunks for embedding. |
| `clean_text_for_embedding()` | `(text) → str` | Strips URLs, Nostr references, and emoji shortcodes. |
| `is_gibberish()` | `(text) → bool` | Entropy-based spam detection. Rejects texts with entropy < 1.5 or > 6.5 (for texts > 20 chars). |

All async wrappers (`get_embedding_async`, `get_embeddings_batch_async`, `get_image_embedding_async`) delegate to `loop.run_in_executor(self.executor, ...)`.

**Vector DB methods:**

| Method | Description |
|--------|-------------|
| `add_vector_by_emb(post_id, hash_id, vector, ...)` | Insert a pre-computed vector into LanceDB. Increments `inserts_since_optimize` and `inserts_since_centroids_update`. Triggers `optimize_index()` every 500 inserts and invalidates centroid cache every `_centroids_update_threshold` inserts. |
| `add_vector_async(post_id, hash_id, text, ...)` | Full pipeline: language detection → gibberish check → embedding → `add_vector_by_emb()`. Used by `/index_document`. |
| `delete_vector(hash_id)` | Delete a single row by hash_id from LanceDB. |
| `find_duplicate_by_vector(vector, threshold=0.95, hours=24)` | Search LanceDB for near-duplicate vectors within a time window. Returns `hash_id` or `None`. |
| `optimize_index()` | Create INT8 IVF-PQ index on LanceDB `vector` column with 256 partitions and 96 sub-vectors. Triggered every 500 inserts. |

**Centroid & routing methods:**

| Method | Description |
|--------|-------------|
| `compute_centroids(n_clusters=10)` | Run KMeans on up to 100K local vectors. Returns `n_clusters` centroid vectors (384-dim). Updates `last_cluster_post_count`. |
| `update_global_map(peer_id, centroids, cluster_ids)` | Replace all centroids for a peer in `global_knowledge_map`. Rebuilds `NearestNeighbors` model. |
| `route_query(query_vector, top_k=3)` | Find top-K peer_ids whose centroids are closest to the query. Uses `nn_model.kneighbors()`. Used by `federated_search()`. |

**Phase 1.5 — Semantic sharding methods:**

| Method | Description |
|--------|-------------|
| `_get_my_centroids(n_clusters=20)` | Returns cached local centroids. Recomputes via `compute_centroids()` if cache is stale (TTL exceeded) or `None`. Resets `inserts_since_centroids_update`. |
| `is_my_shard(vector) → bool` | Core shard routing decision: compare max cosine similarity to my centroids vs foreign centroids from `global_knowledge_map`. Feature flag disabled → always `True`. Fallback: no local centroids or no foreign centroids → `True`. |
| `route_vector_to_node(vector) → str \| None` | Returns the `peer_id` of the node whose centroid is closest to the vector. Uses `nn_model.kneighbors(n_neighbors=1)`. Returns `None` if no model available. |

**Cache system:**

| Cache | Type | Max size | TTL | Key | Value |
|-------|------|----------|-----|-----|-------|
| Embedding cache | `OrderedDict` (LRU) | 100,000 | 1 hour | Clean text string | `(vector, timestamp)` |
| Search cache | `dict` | 20,000 | 5 minutes | Cache key string | `(results, timestamp)` |

### 3.3 `crawler.py` — Search Crawler

**Class:** `SearchCrawler` — subscribes to the storage-node PubSub feed and indexes new content.

**Key fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `vector_brain` | `VectorBrain` | Reference to the embedding & storage service |
| `http_client` | `httpx.AsyncClient` | Shared HTTP client for peer vector forwarding |
| `gateways` | `list[str]` | Storage-node gateway addresses (host:port) |
| `consensus_url` | `str` | gRPC address for consensus-node verification |

**Crawl loop** (`crawl_loop()`):
1. Connect to `ws://{gateway}/api/v1/pubsub/subscribe/feedo_new_events` via WebSocket
2. Round-robin between configured gateways on disconnect
3. Parse JSON events: validate `hash_id` + non-empty `text` (≥5 chars)
4. Buffer events in `pending_events` list — flush when 32 events accumulated or 1 second elapsed
5. On WebSocket close: flush remaining events

**Batch flush** (`_flush_batch(events)`):
1. Extract all texts → `get_embeddings_batch_async(texts)` → batch embeddings
2. For each (event, chunk_embeddings):
   - Extract first chunk vector: `chunk_embeddings[0]` (384-dim)
   - **Phase 1.5**: Call `is_my_shard(vector)`
     - `True` → `add_vector_by_emb()` locally
     - `False` → `route_vector_to_node(vector)` → if target found:
       - `_forward_vector_to_peer(target_url, event, vector)` (HTTP POST to `/p2p/index_vector`)
       - On forward failure or no target → fallback: `add_vector_by_emb()` locally

**Peer forwarding** (`_forward_vector_to_peer(target_url, event, vector) → bool`):
- POST `{target_url}/p2p/index_vector` with JSON body containing all event fields + vector
- Timeout: 5.0 seconds (configurable via `SHARD_FORWARD_TIMEOUT`)
- Returns `True` on HTTP 200, `False` on error/timeout

### 3.4 `p2p.py` — P2P Network

**Class:** `P2PNetwork` — manages centroid handshake broadcasts and federated search.

**Key fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `vector_brain` | `VectorBrain` | Reference for centroid computation |
| `my_url` | `str` | This node's self-identified URL |
| `known_peers` | `set[str]` | Known peer URLs (from `KNOWN_PEERS` env + discovered via handshake) |
| `client` | `httpx.AsyncClient` | HTTP client for P2P communication (timeout 5s) |

**Phase 1.5 event-driven fields:**

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `_last_broadcasted_centroids` | `list[list[float]]` | `[]` | Previous broadcast for drift detection |
| `_last_broadcast_time` | `float` | `0.0` | Timestamp of last broadcast |
| `_event_driven_enabled` | `bool` | `true` | Feature flag: `EVENT_DRIVEN_CENTROIDS` |
| `_centroid_similarity_threshold` | `float` | `0.9` | Cosine similarity threshold for broadcast |

**Centroid broadcast loop** (`broadcast_centroids_loop()`):
```
while True:
    elapsed = 0
    while elapsed < 10 minutes:
        if event_driven_enabled:
            if inserts_since_centroids_update == 0 AND centroid_cache is None:
                # Cache was invalidated — centroids may have drifted
                new_centroids = _get_my_centroids()
                if centroids_changed_significantly(new_centroids):
                    do_broadcast(new_centroids, reason="event-driven")
        sleep 10 seconds
        elapsed += 10

    # Periodic broadcast (every 10 minutes, unconditional)
    centroids = compute_centroids()
    do_broadcast(centroids, reason="periodic")
```

**Centroid drift detection** (`_centroids_changed_significantly(new_centroids) → bool`):
1. If no previous broadcast → `True` (always send first time)
2. If shape mismatch (different K) → `True`
3. For each new centroid, find the most similar old centroid (max cosine similarity)
4. Average the max similarities across all new centroids
5. Return `avg_similarity < threshold` (0.9 default)

**Broadcast** (`_do_broadcast(centroids, reason)`):
1. Build payload: `{peer_id: my_url, centroids, cluster_ids}`
2. POST to each `known_peers` → `/p2p/handshake`
3. Update `_last_broadcasted_centroids` and `_last_broadcast_time`

**Federated search** (`federated_search(query_vector, query_text, ttl, top_k)`):
1. `route_query(query_vector, top_k)` → target peers
2. Skip self (`my_url`)
3. POST `/p2p/search` with `{query: query_text, ttl: ttl-1}` to each target
4. `asyncio.gather(*tasks)` → aggregate results from all peers
5. Return merged `list[dict]`

### 3.5 `storage_adapters.py` — Storage Adapters

**Abstract base:** `BaseStorageAdapter` with two async methods:
- `get_new_hashes() → list[str]`
- `download_file(hash_id) → bytes | None`

**FeedoStorageAdapter:**
- Connects to storage-node HTTP API (`STORAGE_NODE_URL`)
- `get_new_hashes()`: calls `GET /api/files/recent` → extracts `hashes` list
- `download_file(hash_id)`: calls `GET /download/{hash_id}` → returns raw bytes

**IPFSStorageAdapter:**
- Connects to IPFS gateway (`https://ipfs.io/ipfs/` by default)
- `get_new_hashes()`: returns empty list (IPFS has no global feed)
- `download_file(hash_id)`: calls `GET {gateway}{hash_id}` → returns raw bytes

---

## 4. Semantic Sharding Protocol (Phase 1.5)

### 4.1 Principle

Semantic sharding is analogous to a Distributed Hash Table (DHT), but instead of `hash(key) % N`, it uses **semantic proximity** — KMeans centroids partition the embedding space into N regions (shards). Each node stores only the vectors closest to its own centroids. Documents about technology naturally land on one node, cooking recipes on another.

### 4.2 Write routing

```
New Vector
    │
    ▼
is_my_shard(vector)?
    │
    ├── YES → add_vector_by_emb() → LanceDB (local)
    │          Reason: this vector is closer to my centroids
    │
    └── NO  → route_vector_to_node(vector) → target_url
               │
               ├── target found → POST /p2p/index_vector → remote LanceDB
               └── target None  → add_vector_by_emb() → LanceDB (local fallback)
                                  Reason: no global map yet, safe default
```

**Fallbacks (always safe):**
- `SEMANTIC_SHARDING_ENABLED=false` → `is_my_shard()` always returns `True` (full replication mode)
- `global_knowledge_map` empty → `is_my_shard()` returns `True` (solo node)
- No local centroids yet → `is_my_shard()` returns `True` (new node building its index)
- `route_vector_to_node()` returns `None` → local `add_vector_by_emb()` (no routing target)
- Forward HTTP fails → local `add_vector_by_emb()` (network resilience)

### 4.3 Read routing (federated search)

```
Query Vector
    │
    ▼
route_query(query_vector, top_k)
    │  NearestNeighbors.kneighbors() over global_knowledge_map
    ▼
target_peers = [peer_url_1, peer_url_2, ...]  (top-K by centroid proximity)
    │
    ▼
federated_search(query_vector, text, ttl, top_k)
    │  POST /p2p/search to each target_peer
    │  asyncio.wait_for(timeout=2.0)
    ▼
merged_results = local + federated, sorted by score, deduplicated by hash_id
```

The same centroids used for write routing ensure queries are routed to nodes that actually store relevant content — because the query vector will be closest to the centroids of the nodes that indexed similar documents.

### 4.4 Event-driven centroid updates

```
add_vector_by_emb() called
    │  insert_since_centroids_update += 1
    │  if counter >= threshold (100):
    │      reset counter
    │      invalidate centroid cache (_my_centroids_cache = None)
    ▼
broadcast_centroids_loop() (every 10 seconds)
    │  if cache is None (was invalidated):
    │      recompute centroids via _get_my_centroids()
    │      if centroids_changed_significantly(new):
    │          _do_broadcast(new, reason="event-driven")
    │          → POST /p2p/handshake to all known_peers
```

This ensures that when a shard's semantic focus shifts (e.g., a node receives many new vectors about a different topic), peers are notified immediately rather than waiting up to 10 minutes.

### 4.5 Feature flags

| Variable | Default | Effect |
|----------|---------|--------|
| `SEMANTIC_SHARDING_ENABLED=true` | `true` | `is_my_shard()` performs actual comparison |
| `SEMANTIC_SHARDING_ENABLED=false` | | `is_my_shard()` always returns `True` (full replication) |
| `EVENT_DRIVEN_CENTROIDS=true` | `true` | Check for centroid drift every 10 seconds |
| `EVENT_DRIVEN_CENTROIDS=false` | | Only periodic broadcast (every 10 minutes) |

---

## 5. Configuration

All configuration is via environment variables.

### Server

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PORT` | int | `8000` | HTTP server port |
| `HOST` | str | `127.0.0.1` | Listen host |
| `LANCE_DB_PATH` | path | `./lancedb_data` | LanceDB database directory |

### Storage & Gateways

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `GATEWAYS` | str | (empty) | Comma-separated gateway host:port pairs (e.g. `node1:8040,node2:8040`) |
| `STORAGE_NODE_URL` | str | `http://127.0.0.1:8040` | Fallback single gateway URL |

### P2P Networking

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `KNOWN_PEERS` | str | (empty) | Comma-separated peer search-node URLs (e.g. `http://node1:8000,http://node2:8000`) |
| `PUBLIC_API_URL` | str | (empty) | Public-facing URL for self-identification in handshakes |

### Phase 1.5 — Semantic Sharding

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SEMANTIC_SHARDING_ENABLED` | bool | `true` | Enable/disable write routing (`true`/`false`/`1`/`0`/`yes`/`no`) |
| `SHARD_CENTROID_CACHE_TTL` | int | `600` | Local centroid cache TTL in seconds (10 minutes) |
| `SHARD_CENTROID_UPDATE_THRESHOLD` | int | `100` | Number of new vectors before centroid cache invalidation |
| `SHARD_FORWARD_TIMEOUT` | float | `5.0` | HTTP timeout (seconds) for `/p2p/index_vector` forwarding |
| `EVENT_DRIVEN_CENTROIDS` | bool | `true` | Enable event-driven centroid broadcast |
| `CENTROID_CHANGE_THRESHOLD` | float | `0.9` | Minimum average cosine similarity to skip broadcast |

### Legacy (Pinata)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PINATA_API_KEY` | str | (empty) | Pinata API key for IPFS pinning |
| `PINATA_SECRET_API_KEY` | str | (empty) | Pinata API secret |

---

## 6. HTTP API Reference

Base URL: `http://{host}:{PORT}` (default `http://127.0.0.1:8000`)

### 6.1 Vector search

```
GET /query?text={query}&limit=50&federated=true&item_type=all&offset=0
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text` | string | (required) | Search query text |
| `limit` | int | `50` | Max results to return |
| `federated` | bool | `true` | Enable federated search across peers |
| `item_type` | string | `all` | Filter by content type: `text`, `website`, `document`, `all` |
| `offset` | int | `0` | Pagination offset |

**Response:** `200 OK` — JSON:
```json
{
    "results": [
        {
            "hash_id": "bf1fd1300fcfc0acc086986564f64e70c...",
            "item_type": "website",
            "text": "Welcome to Feedo Test Site...",
            "author": "",
            "metadata": {
                "title": "Feedo Search Test Site",
                "description": "A test website..."
            },
            "score": 0.863,
            "duplicates": [
                {
                    "hash_id": "bf1fd1300fcfc0...",
                    "domain": "example.com",
                    "url": "https://example.com",
                    "source_type": "pubsub",
                    "text": "...",
                    "metadata": {...}
                }
            ]
        }
    ]
}
```

Results are sorted by score descending. Duplicate `hash_id` entries are grouped under the primary result's `duplicates` list. Missing text is fetched from storage-node DHT.

**Example:**
```bash
curl "http://127.0.0.1:8000/query?text=blockchain+consensus&limit=10&item_type=document"
```

### 6.2 Latest documents

```
GET /documents?limit=50&offset=0&item_type=all
```

Returns the most recently indexed documents sorted by timestamp.

**Response:** `200 OK` — JSON: `{"results": [{...}]}` (same schema as query results, minus `score` and `duplicates`).

### 6.3 Index document

```
POST /index_document
Content-Type: application/json
```

**Request body:**
```json
{
    "hash_id": "unique-doc-id",
    "text": "Document text content",
    "item_type": "document",
    "author": "did:feedo:abc123...",
    "metadata": {"topic": "consensus", "tags": ["pbft", "blockchain"]}
}
```

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `hash_id` | Yes | — | Unique content identifier |
| `text` | Yes | — | Document text |
| `item_type` | No | `document` | Content type |
| `author` | No | `""` | Author DID |
| `metadata` | No | `{}` | Arbitrary JSON metadata |

**Response:** `200 OK` — `{"status": "ok"}`

This endpoint uses `add_vector_async()` which performs language detection, gibberish filtering, and fresh embedding generation.

### 6.4 P2P handshake

```
POST /p2p/handshake
Content-Type: application/json
```

**Request body:**
```json
{
    "peer_id": "http://node2:8000",
    "centroids": [[0.1, -0.2, ...], [0.3, 0.15, ...]],
    "cluster_ids": ["cluster_0", "cluster_1"]
}
```

Called by other search-nodes to share their KMeans centroids. This node updates its `global_knowledge_map` and rebuilds the `NearestNeighbors` model for query/vector routing.

**Response:** `200 OK` — `{"status": "ok"}`

### 6.5 P2P search (federated)

```
POST /p2p/search
Content-Type: application/json
```

**Request body:**
```json
{
    "query": "blockchain consensus",
    "ttl": 2
}
```

Called by peer nodes during federated search. `ttl` is decremented each hop; search stops when `ttl` reaches 0.

**Response:** `200 OK` — JSON: `{"query": "...", "results": [{...}]}`

### 6.6 P2P index vector (Phase 1.5)

```
POST /p2p/index_vector
Content-Type: application/json
```

**Request body:**
```json
{
    "post_id": 123456,
    "hash_id": "bf1fd1300fcfc0...",
    "vector": [0.01, -0.02, ...],
    "text": "Document text",
    "source_type": "pubsub",
    "item_type": "text",
    "author": "",
    "metadata": "{\"domain\":\"example.com\"}"
}
```

Called by peer nodes to forward a pre-computed vector for local indexing. The receiving node calls `add_vector_by_emb()` directly — no shard check, no re-embedding. Trusts the sender's routing decision.

**Response:** `200 OK` — `{"status": "ok"}`

### 6.7 Explorer stats

```
GET /explorer/stats
```

**Response:** `200 OK` — JSON:
```json
{
    "active_nodes": 3,
    "indexed_posts": 15234,
    "network_health": "Healthy"
}
```

- `network_health`: `"Healthy"` if `active_nodes > 1`, otherwise `"Syncing"`

### 6.8 Known peers

```
GET /v1/node/peers
```

**Response:** `200 OK` — JSON: `{"peers": ["http://node2:8000", "http://node3:8000"]}`

### 6.9 Publish website (storage-node)

```
POST /proxy/publish_feedo
Content-Type: multipart/form-data
```

Uploads a `.zip` file containing a static website. The search-node:
1. Extracts the zip
2. Parses `index.html` for `<title>`, `<meta name="description">`, and text content
3. Uploads the zip to storage-node via `POST /upload`
4. Searches for favicon files and uploads separately
5. Indexes the extracted text in LanceDB

**Response:** `200 OK` — JSON:
```json
{
    "cid": "bf1fd1300fcfc0acc086986564f64e70c759a4d8bde5e05f57b740705ca7c875",
    "title": "My Website",
    "icon_cid": "bafybei..."
}
```

### 6.10 Publish website (Pinata)

```
POST /proxy/publish
Content-Type: multipart/form-data
```

Same as `/proxy/publish_feedo` but uploads to Pinata IPFS instead of storage-node. Requires `PINATA_API_KEY` and `PINATA_SECRET_API_KEY`.

### 6.11 Delete (storage-node)

```
DELETE /proxy/unpin_feedo/{cid}
```

Deletes from storage-node (`DELETE /delete/{cid}`) and removes from local LanceDB index.

### 6.12 Delete (Pinata)

```
DELETE /proxy/unpin/{cid}
```

Unpins from Pinata and removes from local LanceDB index.

---

## 7. P2P Protocol Details

### 7.1 Centroid handshake protocol

- **Endpoint**: `POST /p2p/handshake`
- **Initiator**: Each node broadcasts to all `known_peers`
- **Frequency**: 
  - **Periodic**: every 10 minutes (unconditional)
  - **Event-driven**: when centroid cache is invalidated (100+ new vectors) AND centroid similarity drops below `CENTROID_CHANGE_THRESHOLD` (0.9)
- **Payload**: `{peer_id: url, centroids: [[f32; 384]; K], cluster_ids: [str; K]}`
- **K (number of centroids)**: 20 per node
- **Processing**: Receiver calls `update_global_map()` — removes old centroids for this peer, adds new ones, rebuilds `NearestNeighbors` model on the full `global_knowledge_map`

### 7.2 Federated search protocol

- **Endpoint**: `POST /p2p/search`
- **Payload**: `{query: str, ttl: int}`
- **TTL**: Starts at 3 from the originating `/query` call. Decremented by 1 each hop. Search stops when `ttl ≤ 0`.
- **Timeout**: 2.0 seconds for the entire federated call (`asyncio.wait_for(asyncio.gather(...), timeout=2.0)`)
- **Routing**: `route_query(query_vector, top_k)` — NearestNeighbors search over `global_knowledge_map` centroids. Returns top-K peer URLs whose centroids are closest to the query vector.
- **Aggregation**: Results from all peers are merged, sorted by score descending, and deduplicated by `hash_id`.

### 7.3 Vector forwarding protocol (Phase 1.5)

- **Endpoint**: `POST /p2p/index_vector`
- **Purpose**: Write-side of semantic sharding — forward a pre-computed vector to the node that should store it
- **Payload**: `{post_id, hash_id, vector: [f32; 384], text, source_type, item_type, author, metadata}`
- **Processing**: Receiver calls `add_vector_by_emb()` directly — **no shard validation** (trust-based), **no re-embedding** (vector is already computed)
- **Timeout**: `SHARD_FORWARD_TIMEOUT` (default 5.0 seconds) for the HTTP POST
- **Fallback**: If forwarding fails (timeout, connection error, non-200 status), the sending node indexes the vector locally as a safe default

### 7.4 Global knowledge map

The `global_knowledge_map` is a list of all centroids from all known peer nodes:

```python
# Format
[
    {"centroid": [0.1, -0.2, ...], "peer_id": "http://node2:8000", "cluster_id": "cluster_0"},
    {"centroid": [0.3, 0.15, ...], "peer_id": "http://node2:8000", "cluster_id": "cluster_1"},
    ...
]
```

This data structure serves two purposes:
- **Read routing**: `route_query()` finds which peers' centroids are closest to the query
- **Write routing**: `is_my_shard()` compares local centroids against foreign centroids to decide whether to index locally or forward

The `NearestNeighbors` model is rebuilt (via `sklearn.neighbors.NearestNeighbors.fit()`) every time `update_global_map()` is called — typically on each handshake reception.

---

## 8. Testing

### 8.1 Integration test

Located in `tests/test_search.py`. Spawns 1 real storage-node (Rust binary) + 1 search-node (Python process).

```bash
# Prerequisites:
#   - storage-node binary: cargo build --bin storage-node
#   - Python deps: pip install -r requirements.txt

cd microservices/search-node
python tests/test_search.py
```

**Test cases (7, ~2-3 minutes):**

| # | Test | Description |
|---|------|-------------|
| 1 | Publish website | Upload test zip via `/proxy/publish_feedo`, verify SHA256 hash |
| 2 | Download verification | `GET /download/{hash}` from storage-node matches original zip |
| 3 | Search query | `GET /query?text=Feedo+test+website` finds the published site |
| 4 | Relevance | `GET /query?text=zebrabanana123` (unique keyword) returns site as top result with score > 0.5 |
| 5 | Emoji support | Publish site with emoji content, verify it appears in search |
| 6 | Index document | `POST /index_document` → search for document → verify found |
| 7 | Explorer stats | `GET /explorer/stats` returns indexed_posts ≥ 1 |
| — | Cleanup | Delete test sites from storage-node and search index |

**Configuration for test:**
- `STORAGE_HTTP_PORT=3040`
- `SEARCH_PORT=8001`
- `LANCE_DB_PATH=./lancedb_data_test` (separate from production)
- `KNOWN_PEERS=""` (single-node mode)

### 8.2 Phase 1.5 sharding tests (to be implemented)

Recommended test cases for the new semantic sharding logic:

| Test | What it verifies |
|------|-----------------|
| `test_is_my_shard_disabled` | Feature flag `false` → always returns `True` |
| `test_is_my_shard_empty_global_map` | No foreign centroids → returns `True` (solo fallback) |
| `test_is_my_shard_no_local_centroids` | Empty local table → returns `True` (warmup) |
| `test_is_my_shard_my_closer` | Vector closer to my centroid → `True` |
| `test_is_my_shard_other_closer` | Vector closer to foreign centroid → `False` |
| `test_route_vector_to_node` | Returns correct peer_id for vector closest to that peer's centroid |
| `test_route_vector_to_node_empty` | No model fitted → returns `None` |
| `test_centroids_changed_significantly` | Significant drift → returns `True` |
| `test_centroids_not_changed` | Identical centroids → returns `False` |

---

## 9. Dependencies

| Package | Version | Why |
|---------|---------|-----|
| `fastapi` | 0.110 | HTTP server framework (async, type-validated) |
| `uvicorn` | 0.27 | ASGI server for FastAPI |
| `pydantic` | 2.6 | Request/response model validation |
| `lancedb` | 0.5 | Embedded vector database (columnar, IVF-PQ indexing) |
| `sentence-transformers` | 2.5 | ML embedding models — `multilingual-e5-small` (384-dim text) + `clip-ViT-B-32` (512-dim image) |
| `scikit-learn` | 1.4 | KMeans clustering (`compute_centroids`) + NearestNeighbors (`route_query`, `route_vector_to_node`) |
| `numpy` | 1.26 | Vectorised linear algebra for centroid comparison and routing |
| `httpx` | 0.27 | Async HTTP client for P2P handshakes, federated search, and vector forwarding |
| `aiohttp` | 3.9 | HTTP client for DHT text fetching in search results |
| `websockets` | 12.0 | WebSocket client for PubSub crawler subscription |
| `langdetect` | 1.0 | Automatic language detection during indexing (runs in `ThreadPoolExecutor`) |
| `Pillow` | 10.2 | Image loading and preprocessing for CLIP embeddings |
| `onnxruntime` | 1.17 | ONNX runtime (pre-loaded, for future GPU inference via Triton/ONNX) |
| `grpcio` | 1.62 | gRPC client for consensus-node `VerifyUploadRights` verification |
| `grpcio-tools` | 1.62 | gRPC code generation tools |
| `beautifulsoup4` | 4.12 | HTML parsing for website publish (title, meta description extraction) |
| `python-multipart` | 0.0.9 | Multipart form parsing for file upload endpoints |
| `torch` | (via sentence-transformers) | PyTorch runtime for model inference |

---

## 10. Known Issues & Future Work

### 10.1 Known issues

| Issue | Impact | Fix planned |
|-------|--------|-------------|
| **Full replication without sharding** | When `SEMANTIC_SHARDING_ENABLED=false`, every node stores 100% of the index. 3 nodes = 3 copies. | Phase 1.5 (done) — feature flag now defaults to `true` |
| **Base model without fine-tuning** | `multilingual-e5-small` is a general-purpose model. Short queries ("recipe for zucchini") and long documents may have low cosine similarity. | Phase 2 — fine-tuned `feedo-search-v1` model |
| **CPU-only inference** | Python GIL + `ThreadPoolExecutor` limits concurrent inference. Max throughput ~50 QPS. | Phase 3 — separate GPU inference service |
| **langdetect blocks event loop** | `detect()` is synchronous but now wrapped in `run_in_executor()` (Phase 1). Still adds latency per document. | Acceptable for current scale; GPU inference (Phase 3) eliminates this bottleneck |
| **Image embedding is synchronous** | `requests.get()` + `PIL.Image.open()` in `get_image_embedding()`. Runs in executor but still has overhead. | Phase 3 — GPU inference service will handle images |
| **No monitoring** | No Prometheus metrics, no Grafana dashboards. Latency, cache hit rate, QPS, index size are unknown. | Phase 5 — `/metrics` endpoint |
| **Periodic centroid broadcast (10 min)** | New content may be invisible to other nodes for up to 10 minutes. Event-driven updates (Phase 1.5) mitigate this but check every 10 sec, not instant. | Phase 4 — real-time push model |
| **Federated search timeout is fixed** | 2.0 seconds hardcoded. One slow node can delay the entire query. | Phase 4 — adaptive timeouts + partial results |
| **Search cache key is not shown** | Cache invalidation strategy undocumented. | Document in Phase 5 |
| **No gRPC server** | Search-node only exposes HTTP REST. Other nodes must use HTTP for P2P calls. | Low priority — HTTP is simpler for Python |

### 10.2 Roadmap

See [SEARCH_ROADMAP.md](./SEARCH_ROADMAP.md) for the full 6-phase scaling plan.

| Phase | Status | Key deliverables |
|-------|--------|-----------------|
| **Phase 1** | ✅ Done | Performance baseline: cache tuning (100K emb, 20K search), rate limiting, batch crawler, 10-min centroid interval |
| **Phase 1.5** | ✅ Done | Semantic sharding: `is_my_shard()`, `route_vector_to_node()`, `/p2p/index_vector` endpoint, event-driven centroid updates, feature flags |
| **Phase 2** | Planned | Fine-tuned search model (`feedo-search-v1`) using contrastive learning on click data |
| **Phase 3** | Planned | GPU inference service (Triton/ONNX), decoupled from search event loop |
| **Phase 4** | Planned | Real-time federation: push-model centroid updates, multi-WebSocket crawler, backpressure |
| **Phase 5** | Planned | Multi-modal search, personalised ranking, Prometheus metrics + Grafana dashboards |

### 10.3 Architectural decisions

| Decision | Rationale |
|----------|-----------|
| **LanceDB over Qdrant/Milvus** | Embedded (no separate service), columnar format, IVF-PQ indexing built-in. Suitable for prototype and early phases. Semantic sharding (Phase 1.5) solves the distribution problem without changing DB. |
| **Cosine distance over Euclidean** | Standard for semantic search with normalised embeddings. Cosine distance = `1.0 - cosine_similarity`. |
| **ThreadPoolExecutor over asyncio for inference** | `sentence-transformers` is CPU-bound and not natively async. Thread pool with `os.cpu_count()` workers provides parallelism within GIL constraints. |
| **KMeans for shard boundaries** | Already computed for federated search routing. Reusing the same centroids for write routing avoids additional infrastructure. |
| **Trust-based vector forwarding** | Receiving node does not re-validate `is_my_shard()` for forwarded vectors. Rationale: the sender already made this decision; re-validation would add latency. Hash-based deduplication in `/query` catches any mistakes. |

---

## Appendix: Quick Reference

### Start the node

```bash
cd microservices/search-node
pip install -r requirements.txt
python main.py
```

### Environment

```bash
# Minimal single-node setup
export PORT=8000
export STORAGE_NODE_URL=http://127.0.0.1:8040
export KNOWN_PEERS=""
python main.py
```

```bash
# Multi-node with semantic sharding
export PORT=8001
export STORAGE_NODE_URL=http://storage-node:8040
export KNOWN_PEERS="http://search-node-0:8000,http://search-node-2:8002"
export SEMANTIC_SHARDING_ENABLED=true
export EVENT_DRIVEN_CENTROIDS=true
python main.py
```

### Docker

```bash
docker build -t feedo-search-node .
docker run -p 8000:8000 \
  -e STORAGE_NODE_URL=http://storage-node:8040 \
  -e KNOWN_PEERS="http://search-node-2:8000" \
  -v ./lancedb_data:/app/lancedb_data \
  feedo-search-node