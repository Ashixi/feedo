# Search Node — Scalability Roadmap / Roadmap масштабування

> 🌐 **Language / Мова**: [🇺🇦 Українська](#uk) | [🇬🇧 English](#en)

<div id="en">

# Search Node — Scalability Roadmap

> **Goal**: scale search-node from the current ~3-5 nodes (full index replication) to 1,000+ nodes with a sharded index, DuckDuckGo-level search quality, and GPU-accelerated inference.
>
> **Current problem**: Each search node stores a **full local index** in LanceDB — with 3 nodes this means 3 copies of the same vectors. Federated search helps *find* data, but doesn't help *distribute* storage load. Plus Python GIL limits inference to 2 workers.

---

## Current State (baseline)

| Parameter | Value |
|-----------|-------|
| Language | Python 3 (FastAPI + uvicorn) |
| Model | `intfloat/multilingual-e5-small` (384-dim) + `clip-ViT-B-32` (512-dim) |
| Vector DB | LanceDB (embedded, local on disk) |
| Federation | KMeans centroids → P2P handshake → NearestNeighbors routing |
| Centroid Sync | Once every **1 hour** (`p2p.py: broadcast_centroids_loop`) |
| Embedding Cache | LRU OrderedDict ≤ **10,000** entries (`vector_service.py: max_emb_cache`) |
| Search Cache | Dict ≤ **2,000** entries (`vector_service.py: max_search_cache`) |
| Inference | CPU, `ThreadPoolExecutor(max_workers=2)` |
| Indexing | **Each node indexes all content** via WebSocket pub/sub crawler |
| Deduplication | By vector (cosine > 0.95) + by hash_id (duplicate grouping) |
| Multilingual | `langdetect` (synchronous call, blocks event loop) |
| Search | Vector only (cosine distance) |
| Rate limiting | None |
| Image support | CLIP via `get_image_embedding()` (synchronous `requests.get`) |

### Key Architectural Problems

1. **Full index replication**: each node stores all vectors locally. 3 nodes = 3 copies of the same data. Federated search helps *find* data on other nodes (read path), but doesn't help *distribute* storage load (write path). This is the main scaling bottleneck.
2. **Python GIL + 2 workers**: maximum ~2 concurrent inference requests at once. As QPS grows, inference becomes a bottleneck.
3. **Centroids once per hour**: new content is invisible to other search nodes until the next sync cycle. With 10 nodes, this means a new node can be "blind" for up to 60 minutes.
4. **Embedding cache 10,000**: at a flow of >10 posts/sec, the cache overflows in ~16 minutes. After that — repeated computation of the same texts.
5. **Federated search sequential with timeout 5.0**: queries to other nodes go through `asyncio.gather`, but if one of 3 nodes is slow — the client waits 5 seconds.
6. **langdetect blocks event loop**: synchronous call `detect()` in `add_vector_async()` (line `vector_service.py`). At high throughput, this creates latency.
7. **Base model without fine-tuning**: the universal `multilingual-e5-small` is trained on general texts, not search queries. Because of this, a short query ("zucchini recipe") and a long cooking description may have low cosine similarity — the model doesn't know they are "the same thing". A search-specialized model is needed.
8. **No rate limiting**: `/query` can be spammed.
9. **Image embedding synchronous**: `requests.get()` + `PIL.Image.open()` even in ThreadPoolExecutor creates overhead.
10. **No monitoring**: unknown latency, cache hit rate, QPS, index size.

---

## Phase 1: Performance Baseline — Faster Embeddings + Less Lag - DONE✅

**Goal**: Remove the most obvious bottlenecks without architectural changes. Quick wins.

**Expected growth**: QPS from ~10 to ~50, federation lag from 60 min to 10 min.

### What to Change

#### 1.1 `vector_service.py` — increase caches and workers

- **Current code**: `ThreadPoolExecutor(max_workers=2)`, `max_emb_cache = 10000`, `max_search_cache = 2000`.
- **What to do**:
  - `max_workers`: 2 → `os.cpu_count()` (or 4) — more parallel inference
  - `max_emb_cache`: 10,000 → **100,000** + TTL (1 hour) — not just LRU, but also time-based expiration
  - `max_search_cache`: 2,000 → **20,000** + TTL (5 minutes) — frequent search queries are not recomputed
  - `langdetect.detect()` → wrap in `loop.run_in_executor()` — no longer blocks event loop
- **Files**: `vector_service.py`.

#### 1.2 `p2p.py` — reduce centroid sync interval

- **Current code** (line ~53): `asyncio.sleep(60 * 60)` — 1 hour between centroid broadcasts.
- **What to do**: Reduce to **10 minutes** (`asyncio.sleep(60 * 10)`). This reduces federation lag by 6x — new content becomes visible to other nodes in 10 minutes instead of 60.
- **Files**: `p2p.py` — `broadcast_centroids_loop()`.

#### 1.3 `crawler.py` — batch event processing

- **Current code**: each WebSocket event is processed separately via `await self.vector_brain.add_vector_async()` — sequential calls.
- **What to do**: Accumulate events in a buffer (e.g., up to 32 items or up to 1 second) → process via `get_embeddings_batch_async()` → `add_vector_by_emb()` for each. Batch processing is orders of magnitude faster than sequential (one forward pass through the model instead of N).
- **Files**: `crawler.py` — `crawl_loop()`.

#### 1.4 `main.py` — rate limiting + federated search timeout

- **Current code**: no rate limiting. Federated search — `asyncio.gather` with individual timeout 5.0 per httpx request.
- **What to do**:
  - Add in-memory token bucket rate limiter:
    - `/query`: 100 req/sec (public search)
    - `/index_document`: 50 req/sec (indexing)
    - `/p2p/search`: 200 req/sec (internode traffic, don't limit strictly)
  - Federated search: wrap the entire `asyncio.gather` in `asyncio.wait_for(..., timeout=2.0)` — don't wait for slow nodes longer than 2 seconds.
- **Files**: `main.py` — middleware for rate limiting, changes in `client_query()`.

### Phase 1 Result

- QPS grows 5x (more workers + batch processing)
- Federation lag reduced 6x (10 min instead of 60)
- Cache holds 10x more entries
- Rate limiting protects against spam
- Slow federated nodes don't block the entire request

---

## Phase 1.5: Semantic Sharding — Moving Away from Full Index Replication ✅ DONE

**Goal**: Each search node stores only its semantic shard (approximately 1/N of the total index). Moving away from the "everyone stores everything" model — the fastest path to true distribution.

**Expected growth**: from ~5-10 nodes to **~10-50 nodes**. Each node stores ~1/N vectors. 10 nodes = ~10% of index per node (instead of 100%).

**Why this can be done now**:
- KMeans centroids **are already computed** (`compute_centroids()` in `vector_service.py`)
- Federated search **already works** for read path (`route_query()`, `federated_search()`)
- P2P handshake **already exists** (`/p2p/handshake`)
- Global knowledge map **is already built** (`update_global_map()`)
- Only need to add **write routing**: instead of "index everything locally" → "index only what belongs to my semantic shard"

### How Semantic Sharding Works

The current system uses centroids only for **reading** (where to send a search query). Phase 1.5 adds centroid usage for **writing** (which node should index this vector).

**Decision algorithm for a new vector**:
1. Crawler receives new content → embedding is computed
2. `is_my_shard(vector)`:
   - Find the nearest of **my** centroids to this vector → `my_min_dist`
   - Find the nearest of **other** centroids (from `global_knowledge_map`) → `other_min_dist`
   - If `my_min_dist < other_min_dist` → vector belongs to my shard → **index locally**
   - If `other_min_dist < my_min_dist` → send to another node (the one whose centroid is closest)
3. If `global_knowledge_map` is empty (haven't received any handshake yet) → fallback: index locally
4. The other node receives the vector via `POST /p2p/index_vector` and indexes it locally

**Result**: similar documents naturally group on the same nodes. Federated search (already working) automatically directs search queries to the correct shards — because those nodes' centroids will be closest to the query vector.

### What to Change

#### 1.5.1 `vector_service.py` — shard membership determination method

- **What to do**: Add two new methods:
  - `is_my_shard(vector: list[float]) -> bool`:
    1. Get my local centroids (from `compute_centroids()` or cached)
    2. Compute `min_distance` to my centroids
    3. Get other centroids from `global_knowledge_map`
    4. If no other centroids exist → `True` (fallback)
    5. Compute `min_distance` to other centroids
    6. `True` if my centroid is closer
  - `route_vector_to_node(vector: list[float]) -> Option<String>`:
    - Returns the `peer_id` (URL) of the node whose centroid is closest to the vector
    - Uses `nn_model.kneighbors()` for fast search
- **Files**: `vector_service.py` — new methods.

#### 1.5.2 `crawler.py` + `main.py` — write routing

- **Current code**: `crawler.py` always calls `self.vector_brain.add_vector_async()` locally (line ~42).
- **What to do**: Change the logic:
  1. Compute embedding for text (as before)
  2. Call `vector_brain.is_my_shard(vector)`
  3. If `True` → local `add_vector_by_emb()` (as now)
  4. If `False` → get `target_node_url` via `route_vector_to_node()` → HTTP POST to `{target_node_url}/p2p/index_vector` with JSON body `{post_id, hash_id, vector, text, source_type, ...}`
- **New endpoint** in `main.py`: `POST /p2p/index_vector` — accepts a vector from another node and calls `brain.add_vector_by_emb()` locally.
- **Files**: `crawler.py` — modify `crawl_loop()`, `main.py` — new endpoint.

#### 1.5.3 `p2p.py` — trigger centroid update on significant changes

- **Current code**: centroids are sent only by timer (every 10 min after Phase 1).
- **What to do**: Add a check: after every N new vectors (e.g., 100), recompute centroids and compare with previous ones. If `cosine_similarity(new_centroids, old_centroids) < 0.9` — immediately send handshake, without waiting for the timer.
- **Files**: `p2p.py` — `broadcast_centroids_loop()`.

### Phase 1.5 Result

- Each node stores ~1/N vectors (where N is the number of search nodes)
- No duplication: a site is indexed **once** on the node whose centroids are closest
- 3 nodes: ~33% of index per node (instead of 100% per node)
- 10 nodes: ~10% of index per node
- 50 nodes: ~2% of index per node
- Federated search automatically directs queries to the correct shards (already works via `route_query()`)
- **The "everyone stores everything" model is eliminated in this phase**

> **Analogy**: This works like a Distributed Hash Table (DHT): `hash(key) % N` determines which node stores the data. But instead of a hash, **semantic proximity** is used — KMeans centroids divide the semantic space into N shards. Technology documents go to one node, cooking content to another.

---

## Phase 2: Fine-tuned Search Models — Custom Models for Search 🔶

**Goal**: Instead of the universal `multilingual-e5-small` — a custom embedding model, fine-tuned specifically on search data. The model learns that a short search query ("zucchini recipe") and a long document (cooking description) are the same thing, even without exact word match.

**When**: Between Phase 1.5 and Phase 3, upon first revenue (GPU needed for training).

**Why this is needed**:
- The current `multilingual-e5-small` model is universal, trained on general texts (Wikipedia, news, books). It is not specialized for search.
- Because of this, a short query and a long document may have low cosine similarity, even if they are about the same thing. "Zucchini recipe" ≠ "Take two young zucchinis, slice into rounds..." — the model doesn't know this.
- Fine-tuning teaches the model that search queries and relevant documents should be closer in vector space, and irrelevant ones — farther apart (contrastive learning).
- A specialized model also better handles synonyms ("zucchini" vs "courgette"), colloquial language, and domain-specific terminology.

### What to Change

#### 2.1 Collect search training data

- **What to do**: Add lightweight tracking to the `/query` endpoint:
  - Log pairs `(query_text, clicked_hash_id)` — which results users open after searching
  - Store in a separate SQLite table (or LanceDB) for future training
  - Anonymized: don't store IP or user_id, only query + hash_id + timestamp
- **Files**: `main.py` — click tracking, new `click_logger.py`.

#### 2.2 Fine-tuned model training (separate process, not in runtime)

- **What to do**: Use contrastive learning (e.g., via `sentence-transformers` adapters):
  - Positive pairs: `(query, clicked_document_text)` — cosine similarity should be high
  - Negative pairs: `(query, random_document_text)` or `(query, shown_but_not_clicked)` — cosine similarity should be low
  - Loss function: MultipleNegativesRankingLoss or CosineSimilarityLoss
  - Result: new model `feedo-search-v1` (based on `multilingual-e5-small`, fine-tuned)
- **Infrastructure**: Separate GPU instance for training (not on production). Training once a week/month with new data.

#### 2.3 `vector_service.py` — model replacement

- **What to do**: After training — replace `self.model = SentenceTransformer('intfloat/multilingual-e5-small')` with `self.model = SentenceTransformer('./models/feedo-search-v1')`.
- Fallback support: if the fine-tuned model is not found — use the base model.
- A/B testing: `GET /query?model=v1` vs `GET /query?model=base` for quality comparison on real traffic.
- **Files**: `vector_service.py` — model loading.

### Phase 2 Result

- "Zucchini recipe" → high cosine similarity with any zucchini cooking description (even without the word "recipe" in the text)
- "How to install Linux" → finds tutorials, even if they say "Ubuntu installation guide"
- Synonyms handled correctly: "zucchini" = "courgette", "laptop" = "notebook"
- Search quality at the level of centralized systems, without losing the flexibility of the vector approach

---

## Phase 3: GPU Inference Service

**Goal**: Inference on GPU instead of CPU. Removes GIL limitations completely. Especially important for the fine-tuned model (Phase 2), which may be larger than the base model.

**Expected growth**: QPS from ~100 to **~1,000+**, inference is no longer a bottleneck.

### What to Change

#### 3.1 New `inference_client.py` — client for GPU service

- **What to do**: Replace direct `self.model.encode()` call with an HTTP/gRPC request to a separate inference service:
  - `encode_batch(texts: list[str]) -> list[list[float]]` — sends a batch of texts, receives embeddings
  - `encode_image(image_url: str) -> list[float]` — separate call for images
  - Fallback support: if GPU service is unavailable → local CPU inference
- **Files**: new `inference_client.py`.

#### 3.2 New `Dockerfile.gpu` — separate container for the model

- **What to do**: Separate Docker container with `sentence-transformers` on GPU:
  - FastAPI server on port 8081
  - Endpoints: `POST /v1/embeddings` (text batch), `POST /v1/image-embedding` (image URL)
  - Automatic GPU usage via `model.to('cuda')`
- **Alternative**: NVIDIA Triton Inference Server (ONNX model) — higher performance, but more complex setup.
- **Files**: new `Dockerfile.gpu`, `inference_server.py` (or Triton config).

#### 3.3 `vector_service.py` — transition to inference_client

- **What to do**: `get_embedding()`, `get_embeddings_batch()`, `get_image_embedding()` → delegate to `inference_client` instead of local model call.
- **Files**: `vector_service.py`.

### Phase 3 Result

- Inference on GPU (1000+ embeddings/sec instead of ~50 on CPU)
- Python GIL no longer limits inference (GPU operates asynchronously)
- Search runs on CPU, inference on GPU — full separation
- Horizontal scaling: more GPU containers can be added
- Fine-tuned model (Phase 2) operates without performance degradation

---

## Phase 4: Real-time Federation — Push Model

**Goal**: Content is searchable within seconds of publication. No "10 minute lag."

**Expected growth**: federation lag from 10 minutes to **<5 seconds**, scaling to ~200-1,000 nodes.

### What to Change

#### 4.1 `p2p.py` — event-driven push model instead of periodic poll

- **Current code**: centroids are broadcast by timer (every 10 minutes).
- **What to do**: Add event-driven mechanism:
  1. After adding N new vectors to a shard (e.g., 50) → check if centroids have changed
  2. If `cosine_similarity(new, old) < 0.9` → immediately broadcast handshake to all known nodes
  3. Gossip component: upon receiving a handshake from another node → if its centroids significantly differ from previous → forward further (gossip propagation)
- **Files**: `p2p.py` — `broadcast_centroids_loop()` → `event_driven_sync()`.

#### 4.2 `crawler.py` — multi-threaded crawler

- **Current code**: one WebSocket connection, round-robin between gateways.
- **What to do**:
  - Support **multiple parallel** WebSocket connections to different gateways simultaneously
  - **Backpressure**: shared indexing queue. If queue > 1,000 — slow down acceptance of new events (but don't disconnect)
  - **Prioritization**: sites (storage_class=site) → process first, social posts → second
- **Files**: `crawler.py` — `crawl_loop()`.

### Phase 4 Result

- New content appears in search <5 seconds after publication
- Push model instead of poll: centroids update instantly on changes
- Multi-threaded crawler: fault tolerance when one gateway goes down
- Backpressure: system doesn't choke under peak loads

---

## Phase 5: Multimodality, Personalization, Analytics

**Goal**: Image search, personalized recommendations, full network visibility.

**Expected growth**: UX quality (images in search, personalized results), operator visibility (metrics).

### What to Change

#### 5.1 Multimodal search

- **Current code**: CLIP is already loaded (`image_model = SentenceTransformer('clip-ViT-B-32')`), `get_image_embedding()` already exists. But image search is not used in `/query`.
- **What to do**: Add image search support:
  - `GET /query?text=cat&include_images=true` → search both text and image_vector
  - `POST /query/image` with `multipart/form-data` (upload image → find similar)
  - Results include `image_url` from metadata
- **Files**: `vector_service.py` — search by `image_vector`, `main.py` — new endpoints.

#### 5.2 Personalized ranking

- **Current code**: `update_user_vector_async()` already exists (line `vector_service.py`), but is not used in `/query`.
- **What to do**: Add `user_did` parameter to `/query`:
  - Get user_vector (accumulated interest)
  - After federated search → rerank results by cosine_similarity(result_vector, user_vector)
  - This gives a personalized feed without a centralized algorithm
- **Files**: `vector_service.py` — `personalized_rerank()`, `main.py` — `client_query()`.

#### 5.3 Prometheus metrics + Grafana

- **What to do**: Add `/metrics` endpoint (Prometheus format):
  - `search_requests_total` — total number of search queries
  - `search_latency_seconds` — p50/p90/p99 latency
  - `cache_hit_ratio` — cache hits/misses ratio for embeddings
  - `index_size` — number of vectors in local shard
  - `active_shards` — number of active search nodes in federation
  - `federated_search_latency_seconds` — latency of federated queries
  - `inference_queue_size` — inference queue size (GPU)
- **Files**: `main.py` — `/metrics` endpoint.

### Phase 5 Result

- Image search: "red dress" → finds photos
- Personalized ranking: each user sees results relevant specifically to them
- Full visibility: operators see network state via Grafana
- Scaling to 1,000+ nodes

---

## What NOT to Do

- ❌ **Elasticsearch** — overkill for this project, centralized solution, not P2P
- ❌ **Throw away LanceDB immediately** — for prototypes and early phases it's perfect. The problem is not the DB, but sharding (solved by Phase 1.5)
- ❌ **Wait for Qdrant/Milvus for sharding** — semantic sharding (Phase 1.5) solves the index distribution problem without changing the DB
- ❌ **Run inference and search in the same event loop** — they should be separated (GPU inference service — Phase 3)
- ❌ **Rely on keyword search (BM25, etc.)** — it filters out good semantic results due to missing exact words. "Zucchini" vs "courgette" — keyword won't find, vector model will. The current architecture correctly uses only vector search. Strengthened through fine-tuning (Phase 2).
- ❌ **Use only Python** for inference in production — GPU service is needed for scaling

---

## Scalability Summary Table

| Phase | Max Search Nodes | Index/Node | QPS/Node | Inference | Model | Complexity |
|-------|------------------|------------|----------|-----------|-------|-----------|
| Current (baseline) | ~3-5 (full replica) | 100% vectors | ~10 | CPU, 2 workers | Base e5-small | — |
| Phase 1 (perf baseline) ✅ | ~5-10 | 100% | ~50 | CPU, N workers | Base e5-small | Low (1-2 days) |
| **Phase 1.5 (semantic sharding) ✅** | **~10-50** | **~1/N** (semantic shard) | **~50** | CPU | Base e5-small | **Medium (3-5 days)** |
| **Phase 2 (fine-tuned model) 🔶** | **~10-50** | **~1/N** | **~100** | CPU | **Feedo-search-v1** (fine-tuned) | **High (1-2 weeks + GPU for training)** |
| Phase 3 (GPU inference) | ~50-200 | ~1/N | ~1,000 | GPU (Triton) | Feedo-search-v1 | High (1-2 weeks) |
| Phase 4 (real-time federation) | ~200-1,000 | ~1/N | ~1,000+ | GPU | Feedo-search-v1 | Medium (3-5 days) |
| Phase 5 (multimodal + metrics) | ~1,000+ | ~1/N | ~1,000+ | GPU | Feedo-search-v1 | Medium (3-5 days) |

### Explanation of Node Count

- **Current (~3-5)**: federation works, but each node stores 100% of the index. 3 nodes = 3 copies. Adding a 4th node brings no benefit — only more duplication.
- **Phase 1.5 (10-50)**: the main bottleneck is removed. Each node stores ~1/N of the index. The ~50 limit is determined by the number of centroid comparisons in `is_my_shard()`: 50 nodes × 20 centroids = 1000 comparisons per vector — acceptable for CPU.
- **Phase 3+ (50-1,000+)**: GPU inference removes CPU constraints. Push model (Phase 4) reduces federation overhead. The true limit is determined by Kademlia routing table size, not search architecture.
- **Phase 5 (1,000+)**: full maturity. Search, images, personalization, metrics — all working on 1,000+ nodes.

---

## Priorities by Impact

Recommended implementation order (highest impact first):

1. **Phase 1** — quick wins: caches, rate limiting, lower federation lag
2. **Phase 1.5** ✅ — **most important phase**: index sharding without changing DB. Moving away from "everyone stores everything." From 5 to 50 nodes
3. **Phase 2** 🔶 — search quality: custom model fine-tuned on search data. "Zucchini recipe" = long cooking description (upon first revenue)
4. **Phase 3** — performance: GPU inference, QPS grows 10x (especially important for fine-tuned model)
5. **Phase 4** — real-time: content in search within seconds
6. **Phase 5** — finishing touches: images, personalization, metrics

---

## Risks and Caveats

- **Phase 1**: Increasing `max_emb_cache` to 100,000 — with 384-dim vectors this is ~150 MB RAM for cache. Memory usage needs monitoring.
- **Phase 1.5**: Main risk — **incorrect shard determination**:
  - If two nodes have very similar centroids → the same vector may be considered "mine" for both → duplication
  - If centroids are not updated in time → a new semantic cluster may not have a "home"
  - **Assertion test needed**: send 1,000 random vectors → verify each vector landed on exactly 1 node
  - **Fallback**: if `global_knowledge_map` is empty — index locally (safe default)
- **Phase 2**: Fine-tuning requires GPU for training and enough clicks. Cold start: in the first weeks the model trains on a small sample → quality may be unstable. A/B test needed before full transition. Also need to maintain dimension compatibility (384-dim) to avoid rebuilding the LanceDB index.
- **Phase 3**: GPU service — separate container, orchestration needed (Docker Compose with GPU support, or Kubernetes with GPU nodes). Model cold start — 30-60 seconds.
- **Phase 4**: Push federation model at 1,000 nodes — centroid change gossip messages can create a storm. Debouncing needed (no more than once every 30 seconds).
- **Phase 5**: Prometheus metrics — separate scraping interval needed. Don't add too many metrics (high cardinality).

---

## Path from Prototype to DuckDuckGo

| Metric | Now | Phase 1 | Phase 1.5 | Phase 2 | Phase 3 | Phase 4 | Phase 5 | DuckDuckGo |
|--------|-----|---------|-----------|---------|---------|---------|---------|------------|
| Search Nodes | 1 | 3-5 | 10-50 | 10-50 | 50-200 | 200-1,000 | 1,000+ | ~500 (est.) |
| Documents | ~100K | ~1M | ~10M | ~10M | ~100M | ~1B | ~10B | ~20B |
| QPS | ~10 | ~50 | ~50 | ~100 | ~1,000 | ~1,000+ | ~1,000+ | ~3,000 |
| Latency p50 | ~500ms | ~200ms | ~200ms | ~100ms | ~50ms | ~20ms | ~10ms | <50ms |
| Quality short→long | Low | Low | Low | ✅ Fine-tuned | ✅ | ✅ | ✅ | ✅ |
| Synonyms | Partial | Partial | Partial | ✅ | ✅ | ✅ | ✅ | ✅ |
| Image Search | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Personalization | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | Partial |
| Indexing Lag | ~60 min | ~10 min | ~10 min | ~10 min | ~10 min | <5 sec | <5 sec | ~seconds |
| Index/Node | 100% | 100% | ~10% (10 nodes) | ~10% | ~2% (50 nodes) | ~0.1% (1K) | ~0.1% | N/A (centr.) |

</div>

<div id="uk">

# Search Node — Roadmap масштабування

> **Мета**: масштабувати search-node з поточних ~3-5 нод (повна реплікація індексу) до 1,000+ нод з шардованим індексом, якістю пошуку рівня DuckDuckGo, та GPU-прискореним inference.
>
> **Актуальна проблема**: Кожна search-нода зберігає **повний локальний індекс** у LanceDB — при 3 нодах це 3 копії тих самих векторів. Federated search допомагає *знаходити* дані, але не *розподіляти* навантаження зберігання. Плюс Python GIL обмежує inference 2 воркерами.

---

## Поточний стан (baseline)

| Параметр | Значення |
|----------|----------|
| Мова | Python 3 (FastAPI + uvicorn) |
| Модель | `intfloat/multilingual-e5-small` (384-dim) + `clip-ViT-B-32` (512-dim) |
| Векторна БД | LanceDB (embedded, локальна на диск) |
| Федерація | KMeans центроїди → P2P handshake → NearestNeighbors routing |
| Синхронізація центроїдів | Раз на **1 годину** (`p2p.py: broadcast_centroids_loop`) |
| Кеш ембеддінгів | LRU OrderedDict ≤ **10,000** записів (`vector_service.py: max_emb_cache`) |
| Кеш пошуку | Dict ≤ **2,000** записів (`vector_service.py: max_search_cache`) |
| Inference | CPU, `ThreadPoolExecutor(max_workers=2)` |
| Індексація | **Кожна нода індексує весь контент** через WebSocket pub/sub crawler |
| Дедуплікація | За вектором (cosine > 0.95) + за hash_id (групування дублікатів) |
| Мультимовність | `langdetect` (синхронний виклик, блокує event loop) |
| Пошук | Тільки векторний (cosine distance) |
| Rate limiting | Відсутній |
| Підтримка зображень | CLIP через `get_image_embedding()` (синхронний `requests.get`) |

### Ключові архітектурні проблеми

1. **Повна реплікація індексу**: кожна нода зберігає всі вектори локально. 3 ноди = 3 копії одних і тих самих даних. Federated search допомагає *знайти* дані на інших нодах (read path), але не допомагає *розподілити* навантаження зберігання (write path). Це головний bottleneck для масштабування.
2. **Python GIL + 2 воркери**: максимум ~2 конкурентні inference-запити одночасно. При зростанні QPS inference стає bottleneck.
3. **Центроїди раз на годину**: новий контент невидимий для інших search-нод до наступного циклу синхронізації. При 10 нодах це означає що нова нода може бути "сліпою" до 60 хвилин.
4. **Кеш ембеддінгів 10,000**: при потоці >10 постів/сек кеш переповнюється за ~16 хвилин. Після цього — повторні обчислення тих самих текстів.
5. **Federated search sequential з timeout 5.0**: запити до інших нод ідуть через `asyncio.gather`, але якщо одна з 3 нод повільна — клієнт чекає 5 секунд.
6. **langdetect блокує event loop**: синхронний виклик `detect()` у `add_vector_async()` (рядок `vector_service.py`). При великому потоці це створює затримки.
7. **Базова модель без fine-tuning**: універсальна `multilingual-e5-small` навчена на загальних текстах, а не на пошукових запитах. Через це короткий запит ("рецепт кабачків") і довгий опис приготування можуть мати низьку cosine similarity — модель не знає, що це "одне й те саме". Потрібна модель, спеціалізована на пошук.
8. **Немає rate limiting**: `/query` можна заспамити.
9. **Image embedding синхронний**: `requests.get()` + `PIL.Image.open()` навіть у ThreadPoolExecutor створює overhead.
10. **Немає моніторингу**: невідомо latency, cache hit rate, QPS, розмір індексу.

---

## Фаза 1: Performance Baseline — швидші ембеддінги + менший lag - DONE✅

**Ціль**: Прибрати найочевидніші bottleneck'и без зміни архітектури. Швидкі перемоги.

**Очікуваний приріст**: QPS з ~10 до ~50, lag федерації з 60 хв до 10 хв.

### Що змінити

#### 1.1 `vector_service.py` — збільшення кешів та воркерів

- **Поточний код**: `ThreadPoolExecutor(max_workers=2)`, `max_emb_cache = 10000`, `max_search_cache = 2000`.
- **Що зробити**:
  - `max_workers`: 2 → `os.cpu_count()` (або 4) — більше паралельних inference
  - `max_emb_cache`: 10,000 → **100,000** + TTL (1 година) — не тільки LRU, а й протухання за часом
  - `max_search_cache`: 2,000 → **20,000** + TTL (5 хвилин) — часті пошукові запити не перераховуються
  - `langdetect.detect()` → загорнути в `loop.run_in_executor()` — більше не блокує event loop
- **Файли**: `vector_service.py`.

#### 1.2 `p2p.py` — зменшення інтервалу синхронізації центроїдів

- **Поточний код** (рядок ~53): `asyncio.sleep(60 * 60)` — 1 година між broadcast центроїдів.
- **Що зробити**: Зменшити до **10 хвилин** (`asyncio.sleep(60 * 10)`). Це в 6 разів зменшує lag федерації — новий контент стає видимим для інших нод через 10 хвилин замість 60.
- **Файли**: `p2p.py` — `broadcast_centroids_loop()`.

#### 1.3 `crawler.py` — batch-обробка подій

- **Поточний код**: кожна подія з WebSocket обробляється окремо через `await self.vector_brain.add_vector_async()` — sequential виклики.
- **Що зробити**: Накопичувати події в буфер (наприклад, до 32 штук або до 1 секунди) → обробляти через `get_embeddings_batch_async()` → `add_vector_by_emb()` для кожного. Batch-обробка в рази швидша за sequential (одне forward pass через модель замість N).
- **Файли**: `crawler.py` — `crawl_loop()`.

#### 1.4 `main.py` — rate limiting + federated search timeout

- **Поточний код**: жодного rate limiting. Federated пошук — `asyncio.gather` з індивідуальним timeout 5.0 на кожен httpx-запит.
- **Що зробити**:
  - Додати in-memory token bucket rate limiter:
    - `/query`: 100 req/sec (публічний пошук)
    - `/index_document`: 50 req/sec (індексація)
    - `/p2p/search`: 200 req/sec (міжнодовий трафік, не обмежувати жорстко)
  - Federated пошук: загорнути весь `asyncio.gather` у `asyncio.wait_for(..., timeout=2.0)` — не чекати повільні ноди більше 2 секунд.
- **Файли**: `main.py` — middleware для rate limiting, зміни в `client_query()`.

### Результат фази 1

- QPS зростає в 5 разів (більше воркерів + batch-обробка)
- Lag федерації зменшується в 6 разів (10 хв замість 60)
- Кеш тримає в 10 разів більше записів
- Rate limiting захищає від спаму
- Повільні federated-ноди не блокують весь запит

---

## Фаза 1.5: Semantic Sharding — відмова від повної реплікації індексу ✅ DONE

**Ціль**: Кожна search-нода зберігає тільки свій семантичний шард (приблизно 1/N від загального індексу). Відмова від моделі «всі зберігають все» — найшвидший шлях до справжньої розподіленості.

**Очікуваний приріст**: з ~5-10 нод до **~10-50 нод**. Кожна нода зберігає ~1/N векторів. 10 нод = ~10% індексу на ноду (замість 100%).

**Чому це можна зробити вже зараз**:
- KMeans центроїди **вже обчислюються** (`compute_centroids()` у `vector_service.py`)
- Federated search **вже працює** для read path (`route_query()`, `federated_search()`)
- P2P handshake **вже є** (`/p2p/handshake`)
- Global knowledge map **вже будується** (`update_global_map()`)
- Потрібно тільки додати **write routing**: замість «індексувати все локально» → «індексувати тільки те, що належить моєму семантичному шарду»

### Як працює Semantic Sharding

Поточна система використовує центроїди тільки для **читання** (куди відправити пошуковий запит). Фаза 1.5 додає використання центроїдів для **запису** (яка нода повинна індексувати цей вектор).

**Алгоритм прийняття рішення для нового вектора**:
1. Crawler отримує новий контент → обчислюється embedding
2. `is_my_shard(vector)`:
   - Знайти найближчий з **моїх** центроїдів до цього вектора → `my_min_dist`
   - Знайти найближчий з **чужих** центроїдів (з `global_knowledge_map`) → `other_min_dist`
   - Якщо `my_min_dist < other_min_dist` → вектор належить моєму шарду → **індексувати локально**
   - Якщо `other_min_dist < my_min_dist` → відправити на іншу ноду (ту, чий центроїд найближчий)
3. Якщо `global_knowledge_map` порожня (ще не отримали жодного handshake) → fallback: індексувати локально
4. Інша нода отримує вектор через `POST /p2p/index_vector` і індексує його локально

**Результат**: схожі документи природно групуються на одних і тих самих нодах. Federated search (уже працює) автоматично направляє пошукові запити до правильних шардів — тому що centroids тих нод будуть найближчими до query vector.

### Що змінити

#### 1.5.1 `vector_service.py` — метод визначення приналежності вектора до шарду

- **Що зробити**: Додати два нових методи:
  - `is_my_shard(vector: list[float]) -> bool`:
    1. Отримати мої локальні центроїди (з `compute_centroids()` або кешовані)
    2. Обчислити `min_distance` до моїх центроїдів
    3. Отримати чужі центроїди з `global_knowledge_map`
    4. Якщо чужих центроїдів немає → `True` (fallback)
    5. Обчислити `min_distance` до чужих центроїдів
    6. `True` якщо мій центроїд ближчий
  - `route_vector_to_node(vector: list[float]) -> Option<String>`:
    - Повертає `peer_id` (URL) ноди, чий центроїд найближчий до вектора
    - Використовує `nn_model.kneighbors()` для швидкого пошуку
- **Файли**: `vector_service.py` — нові методи.

#### 1.5.2 `crawler.py` + `main.py` — write routing

- **Поточний код**: `crawler.py` завжди викликає `self.vector_brain.add_vector_async()` локально (рядок ~42).
- **Що зробити**: Змінити логіку:
  1. Обчислити embedding для тексту (як і раніше)
  2. Викликати `vector_brain.is_my_shard(vector)`
  3. Якщо `True` → локальний `add_vector_by_emb()` (як зараз)
  4. Якщо `False` → отримати `target_node_url` через `route_vector_to_node()` → HTTP POST на `{target_node_url}/p2p/index_vector` з JSON-тілом `{post_id, hash_id, vector, text, source_type, ...}`
- **Новий endpoint** в `main.py`: `POST /p2p/index_vector` — приймає вектор від іншої ноди і викликає `brain.add_vector_by_emb()` локально.
- **Файли**: `crawler.py` — змінити `crawl_loop()`, `main.py` — новий endpoint.

#### 1.5.3 `p2p.py` — тригер оновлення центроїдів при значних змінах

- **Поточний код**: центроїди відправляються тільки за таймером (кожні 10 хв після Фази 1).
- **Що зробити**: Додати перевірку: після кожних N нових векторів (наприклад, 100) перерахувати центроїди і порівняти з попередніми. Якщо `cosine_similarity(new_centroids, old_centroids) < 0.9` — негайно відправити handshake, не чекаючи таймера.
- **Файли**: `p2p.py` — `broadcast_centroids_loop()`.

### Результат фази 1.5

- Кожна нода зберігає ~1/N векторів (де N — кількість search-нод)
- Немає дублювання: сайт індексується **один раз** на тій ноді, чиї центроїди найближчі
- 3 ноди: ~33% індексу на кожну (замість 100% на кожну)
- 10 нод: ~10% індексу на кожну
- 50 нод: ~2% індексу на кожну
- Federated search автоматично направляє запити до правильних шардів (уже працює через `route_query()`)
- **Модель «всі зберігають все» ліквідується вже на цій фазі**

> **Аналогія**: Це працює як розподілений хеш-стіл (DHT): `hash(key) % N` визначає, яка нода зберігає дані. Але замість хешу використовується **семантична близькість** — центроїди KMeans ділять семантичний простір на N шардів. Документи про технології потрапляють на одну ноду, про кулінарію — на іншу.

---

## Фаза 2: Fine-tuned Search Models — власні моделі для пошуку 🔶

**Ціль**: Замість універсальної `multilingual-e5-small` — власна embedding-модель, донавчена спеціально на пошукових даних. Модель вчиться розуміти, що короткий пошуковий запит ("рецепт кабачків") і довгий документ (опис приготування) — це одне й те саме, навіть без exact match слів.

**Коли**: Між Фазою 1.5 та Фазою 3, при першому доході (потрібні GPU для тренування).

**Чому це потрібно**:
- Поточна модель `multilingual-e5-small` — універсальна, навчена на загальних текстах (Wikipedia, новини, книги). Вона не спеціалізована на пошук.
- Через це короткий запит і довгий документ можуть мати низьку cosine similarity, навіть якщо вони про одне й те саме. "Рецепт кабачків" ≠ "Беремо два молодих кабачки, нарізаємо кружальцями..." — модель цього не знає.
- Fine-tuning навчає модель, що пошукові запити та релевантні документи мають бути ближчими у векторному просторі, а нерелевантні — далі (contrastive learning).
- Спеціалізована модель також краще обробляє синоніми ("кабачки" vs "цукіні"), розмовну мову, та специфічну термінологію.

### Що змінити

#### 2.1 Збір пошукових даних для тренування

- **Що зробити**: Додати легкий трекінг у `/query` endpoint:
  - Логувати пари `(query_text, clicked_hash_id)` — які результати користувачі відкривають після пошуку
  - Зберігати в окрему SQLite таблицю (або LanceDB) для подальшого тренування
  - Анонімізовано: не зберігати IP чи user_id, тільки query + hash_id + timestamp
- **Файли**: `main.py` — трекінг кліків, новий `click_logger.py`.

#### 2.2 Тренування fine-tuned моделі (окремий процес, не в рантаймі)

- **Що зробити**: Використовувати contrastive learning (наприклад, через `sentence-transformers` адаптери):
  - Позитивні пари: `(query, clicked_document_text)` — cosine similarity має бути високою
  - Негативні пари: `(query, random_document_text)` або `(query, shown_but_not_clicked)` — cosine similarity має бути низькою
  - Функція втрат: MultipleNegativesRankingLoss або CosineSimilarityLoss
  - Результат: нова модель `feedo-search-v1` (на базі `multilingual-e5-small`, донавчена)
- **Інфраструктура**: Окремий GPU-інстанс для тренування (не на продакшені). Тренування раз на тиждень/місяць з новими даними.

#### 2.3 `vector_service.py` — заміна моделі

- **Що зробити**: Після тренування — замінити `self.model = SentenceTransformer('intfloat/multilingual-e5-small')` на `self.model = SentenceTransformer('./models/feedo-search-v1')`.
- Підтримка fallback: якщо fine-tuned модель не знайдена — використовувати базову.
- A/B тестування: `GET /query?model=v1` vs `GET /query?model=base` для порівняння якості на реальному трафіку.
- **Файли**: `vector_service.py` — завантаження моделі.

### Результат фази 2

- "Рецепт кабачків" → висока cosine similarity з будь-яким описом приготування кабачків (навіть без слова "рецепт" у тексті)
- "Як встановити Linux" → знаходить туторіали, навіть якщо там написано "Ubuntu installation guide"
- Синоніми обробляються коректно: "кабачки" = "цукіні", "ноутбук" = "лептоп"
- Якість пошуку рівня централізованих систем, без втрати гнучкості векторного підходу

---

## Фаза 3: GPU Inference Service

**Ціль**: Inference на GPU замість CPU. Знімає GIL-обмеження повністю. Особливо важливо для fine-tuned моделі (Фаза 2), яка може бути більшою за базову.

**Очікуваний приріст**: QPS з ~100 до **~1,000+**, inference більше не bottleneck.

### Що змінити

#### 3.1 Новий `inference_client.py` — клієнт до GPU-сервісу

- **Що зробити**: Замінити прямий виклик `self.model.encode()` на HTTP/gRPC-запит до окремого inference-сервісу:
  - `encode_batch(texts: list[str]) -> list[list[float]]` — відправляє батч текстів, отримує ембеддінги
  - `encode_image(image_url: str) -> list[float]` — окремий виклик для зображень
  - Підтримка fallback: якщо GPU-сервіс недоступний → локальний CPU-inference
- **Файли**: новий `inference_client.py`.

#### 3.2 Новий `Dockerfile.gpu` — окремий контейнер для моделі

- **Що зробити**: Окремий Docker-контейнер з `sentence-transformers` на GPU:
  - FastAPI сервер на порту 8081
  - Endpoints: `POST /v1/embeddings` (батч текстів), `POST /v1/image-embedding` (URL зображення)
  - Автоматичне використання GPU через `model.to('cuda')`
- **Альтернатива**: NVIDIA Triton Inference Server (ONNX-модель) — вища продуктивність, але складніше налаштування.
- **Файли**: новий `Dockerfile.gpu`, `inference_server.py` (або Triton config).

#### 3.3 `vector_service.py` — перехід на inference_client

- **Що зробити**: `get_embedding()`, `get_embeddings_batch()`, `get_image_embedding()` → делегувати до `inference_client` замість локального виклику моделі.
- **Файли**: `vector_service.py`.

### Результат фази 3

- Inference на GPU (1000+ embeddings/sec замість ~50 на CPU)
- Python GIL більше не обмежує inference (GPU працює асинхронно)
- Пошук відбувається на CPU, inference на GPU — повне розділення
- Горизонтальне масштабування: можна додати більше GPU-контейнерів
- Fine-tuned модель (Фаза 2) працює без деградації продуктивності

---

## Фаза 4: Real-time Federation — Push-модель

**Ціль**: Контент доступний для пошуку за секунди після публікації. Жодного «lag 10 хвилин».

**Очікуваний приріст**: lag федерації з 10 хвилин до **<5 секунд**, масштабування до ~200-1,000 нод.

### Що змінити

#### 4.1 `p2p.py` — подієва push-модель замість періодичного poll

- **Поточний код**: центроїди розсилаються за таймером (кожні 10 хвилин).
- **Що зробити**: Додати event-driven механізм:
  1. Після додавання N нових векторів у шард (наприклад, 50) → перевірити чи змінилися центроїди
  2. Якщо `cosine_similarity(new, old) < 0.9` → негайно розіслати handshake всім відомим нодам
  3. Gossip-компонент: при отриманні handshake від іншої ноди → якщо її центроїди суттєво відрізняються від попередніх → переслати далі (gossip propagation)
- **Файли**: `p2p.py` — `broadcast_centroids_loop()` → `event_driven_sync()`.

#### 4.2 `crawler.py` — багатопотоковий краулер

- **Поточний код**: один WebSocket-коннект, round-robin між gateway.
- **Що зробити**:
  - Підтримка **кількох паралельних** WebSocket-з'єднань до різних gateway одночасно
  - **Backpressure**: спільна черга на індексацію. Якщо черга > 1,000 — сповільнювати прийом нових подій (але не відключатися)
  - **Пріоритезація**: сайти (storage_class=site) → обробляти першими, соціальні пости → другими
- **Файли**: `crawler.py` — `crawl_loop()`.

### Результат фази 4

- Новий контент з'являється в пошуку за <5 секунд після публікації
- Push-модель замість poll: центроїди оновлюються миттєво при змінах
- Багатопотоковий краулер: відмовостійкість при падінні одного gateway
- Backpressure: система не захлинається при пікових навантаженнях

---

## Фаза 5: Мультимодальність, персоналізація, аналітика

**Ціль**: Пошук зображень, персональні рекомендації, повна visibility в мережу.

**Очікуваний приріст**: якість UX (зображення в пошуку, персональні результати), операторська visibility (метрики).

### Що змінити

#### 5.1 Мультимодальний пошук

- **Поточний код**: CLIP уже завантажено (`image_model = SentenceTransformer('clip-ViT-B-32')`), `get_image_embedding()` уже є. Але пошук по зображеннях не використовується в `/query`.
- **Що зробити**: Додати підтримку пошуку зображень:
  - `GET /query?text=cat&include_images=true` → шукати і text, і image_vector
  - `POST /query/image` з `multipart/form-data` (завантажити зображення → знайти схожі)
  - Результати містять `image_url` з метаданих
- **Файли**: `vector_service.py` — пошук по `image_vector`, `main.py` — нові endpoints.

#### 5.2 Персональний ranking

- **Поточний код**: `update_user_vector_async()` уже є (рядок `vector_service.py`), але не використовується в `/query`.
- **Що зробити**: Додати параметр `user_did` у `/query`:
  - Отримати user_vector (накопичений інтерес)
  - Після federated пошуку → переранжувати результати за cosine_similarity(result_vector, user_vector)
  - Це дає персоналізований feed без централізованого алгоритму
- **Файли**: `vector_service.py` — `personalized_rerank()`, `main.py` — `client_query()`.

#### 5.3 Prometheus метрики + Grafana

- **Що зробити**: Додати `/metrics` endpoint (формат Prometheus):
  - `search_requests_total` — загальна кількість пошукових запитів
  - `search_latency_seconds` — p50/p90/p99 latency
  - `cache_hit_ratio` — співвідношення cache hits/misses для ембеддінгів
  - `index_size` — кількість векторів у локальному шарді
  - `active_shards` — кількість активних search-нод у federation
  - `federated_search_latency_seconds` — latency federated запитів
  - `inference_queue_size` — розмір черги на inference (GPU)
- **Файли**: `main.py` — `/metrics` endpoint.

### Результат фази 5

- Пошук зображень: "червона сукня" → знаходить фото
- Персональний ranking: кожен користувач бачить результати, релевантні саме йому
- Повна visibility: оператори бачать стан мережі через Grafana
- Масштабування до 1,000+ нод

---

## Що НЕ треба робити

- ❌ **Elasticsearch** — overkill для цього проекту, централізоване рішення, не P2P
- ❌ **Видаляти LanceDB одразу** — для прототипу і ранніх фаз він ідеальний. Проблема не в БД, а в шардингу (вирішується Фазою 1.5)
- ❌ **Чекати Qdrant/Milvus для шардингу** — semantic sharding (Фаза 1.5) вирішує проблему розподілу індексу без зміни БД
- ❌ **Робити inference і пошук в одному event loop** — вони мають бути розділені (GPU inference сервіс — Фаза 3)
- ❌ **Покладатися на keyword-пошук (BM25 тощо)** — він відсіює хороші семантичні результати через відсутність точних слів. «Кабачки» vs «цукіні» — keyword не знайде, векторна модель знайде. Поточна архітектура правильно використовує тільки векторний пошук. Посилення через fine-tuning (Фаза 2).
- ❌ **Використовувати тільки Python** для inference на продакшені — GPU-сервіс потрібен для масштабування

---

## Підсумкова таблиця масштабованості

| Фаза | Макс. search-нод | Індекс/ноду | QPS/ноду | Inference | Модель | Складність |
|------|------------------|-------------|----------|-----------|--------|-----------|
| Зараз (baseline) | ~3-5 (повна репліка) | 100% векторів | ~10 | CPU, 2 воркери | Базова e5-small | — |
| Фаза 1 (perf baseline) ✅ | ~5-10 | 100% | ~50 | CPU, N воркерів | Базова e5-small | Низька (1-2 дні) |
| **Фаза 1.5 (semantic sharding) ✅** | **~10-50** | **~1/N** (семантичний шард) | **~50** | CPU | Базова e5-small | **Середня (3-5 днів)** |
| **Фаза 2 (fine-tuned model) 🔶** | **~10-50** | **~1/N** | **~100** | CPU | **Feedo-search-v1** (донавчена) | **Висока (1-2 тижні + GPU для тренування)** |
| Фаза 3 (GPU inference) | ~50-200 | ~1/N | ~1,000 | GPU (Triton) | Feedo-search-v1 | Висока (1-2 тижні) |
| Фаза 4 (real-time federation) | ~200-1,000 | ~1/N | ~1,000+ | GPU | Feedo-search-v1 | Середня (3-5 днів) |
| Фаза 5 (multimodal + metrics) | ~1,000+ | ~1/N | ~1,000+ | GPU | Feedo-search-v1 | Середня (3-5 днів) |

### Пояснення щодо кількості нод

- **Зараз (~3-5)**: federation працює, але кожна нода зберігає 100% індексу. 3 ноди = 3 копії. Додавання 4-ї ноди не дає виграшу — тільки більше дублювання.
- **Фаза 1.5 (10-50)**: головний bottleneck знято. Кожна нода зберігає ~1/N індексу. Ліміт ~50 визначається кількістю centroids-порівнянь у `is_my_shard()`: 50 нод × 20 центроїдів = 1000 порівнянь на вектор — прийнятно для CPU.
- **Фаза 3+ (50-1,000+)**: GPU inference знімає CPU-обмеження. Push-модель (Фаза 4) зменшує overhead федерації. Справжній ліміт визначається розміром Kademlia routing table, а не архітектурою пошуку.
- **Фаза 5 (1,000+)**: повна зрілість. Пошук, зображення, персоналізація, метрики — все працює на 1,000+ нодах.

---

## Пріоритети за впливом

Рекомендований порядок впровадження (найбільший impact першим):

1. **Фаза 1** — швидкі перемоги: кеші, rate limiting, менший lag федерації
2. **Фаза 1.5** ✅ — **найважливіша фаза**: шардинг індексу без зміни БД. Відмова від «всі зберігають все». З 5 до 50 нод
3. **Фаза 2** 🔶 — якість пошуку: власна модель, донавчена на пошукових даних. «Рецепт кабачків» = довгий опис приготування (при першому доході)
4. **Фаза 3** — продуктивність: GPU inference, QPS зростає в 10 разів (особливо важливо для fine-tuned моделі)
5. **Фаза 4** — real-time: контент у пошуку за секунди
6. **Фаза 5** — фінальні штрихи: зображення, персоналізація, метрики

---

## Ризики та застереження

- **Фаза 1**: Збільшення `max_emb_cache` до 100,000 — при 384-dim векторах це ~150 MB RAM на кеш. Потрібно моніторити використання пам'яті.
- **Фаза 1.5**: Головний ризик — **неправильне визначення шарду**:
  - Якщо дві ноди мають дуже схожі центроїди → один і той самий вектор може бути визнаний «своїм» для обох → дублювання
  - Якщо центроїди не оновлюються вчасно → новий семантичний кластер може не мати "дому"
  - **Потрібен assertion-тест**: відправити 1,000 випадкових векторів → перевірити що кожен вектор потрапив рівно на 1 ноду
  - **Fallback**: якщо `global_knowledge_map` порожня — індексувати локально (безпечний дефолт)
- **Фаза 2**: Fine-tuning потребує GPU для тренування та достатньої кількості кліків. Холодний старт: перші тижні модель тренується на малій вибірці → якість може бути нестабільною. Потрібен A/B тест перед повним переходом. Також потрібно зберігати сумісність розмірності (384-dim), щоб не перебудовувати LanceDB індекс.
- **Фаза 3**: GPU-сервіс — окремий контейнер, потрібна оркестрація (Docker Compose з GPU support, або Kubernetes з GPU-нодами). Холодний старт моделі — 30-60 секунд.
- **Фаза 4**: Push-модель федерації при 1,000 нодах — gossip-повідомлення про зміну центроїдів можуть створювати шторм. Потрібен дебаунсинг (не частіше ніж раз на 30 секунд).
- **Фаза 5**: Prometheus метрики — потрібен окремий scraping інтервал. Не додавати занадто багато метрик (high cardinality).

---

## Шлях від прототипу до DuckDuckGo

| Метрика | Зараз | Фаза 1 | Фаза 1.5 | Фаза 2 | Фаза 3 | Фаза 4 | Фаза 5 | DuckDuckGo |
|---------|-------|--------|----------|--------|--------|--------|--------|------------|
| Search-ноди | 1 | 3-5 | 10-50 | 10-50 | 50-200 | 200-1,000 | 1,000+ | ~500 (оцінка) |
| Документів | ~100K | ~1M | ~10M | ~10M | ~100M | ~1B | ~10B | ~20B |
| QPS | ~10 | ~50 | ~50 | ~100 | ~1,000 | ~1,000+ | ~1,000+ | ~3,000 |
| Latency p50 | ~500ms | ~200ms | ~200ms | ~100ms | ~50ms | ~20ms | ~10ms | <50ms |
| Якість short→long | Низька | Низька | Низька | ✅ Fine-tuned | ✅ | ✅ | ✅ | ✅ |
| Синоніми | Частково | Частково | Частково | ✅ | ✅ | ✅ | ✅ | ✅ |
| Пошук зображень | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Персоналізація | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | Частково |
| Lag індексації | ~60 хв | ~10 хв | ~10 хв | ~10 хв | ~10 хв | <5 сек | <5 сек | ~секунди |
| Індекс/ноду | 100% | 100% | ~10% (10 нод) | ~10% | ~2% (50 нод) | ~0.1% (1K) | ~0.1% | N/A (центр.) |

</div>