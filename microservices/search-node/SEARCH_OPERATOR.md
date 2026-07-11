# Search Node — Operator Guide

> **Audience**: Node operators who want to run a Feedo search node.
> **Prerequisite knowledge**: Basic Linux administration, Docker, command line.
> For architecture and API details, see [SEARCH_DOCS.md](./SEARCH_DOCS.md).

---

## 1. Prerequisites

### Hardware

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8 GB+ |
| Disk | SSD, 20 GB | SSD, 50 GB+ |
| Network | 10 Mbps, static public IP | 100+ Mbps |

**CPU is the main resource** — search-node runs ML inference on CPU (`sentence-transformers` in a `ThreadPoolExecutor`). 4 vCPU cores handle ~50 queries/second. More cores = more parallel inference workers.

**RAM breakdown**:
- ML models: `multilingual-e5-small` ≈ 470 MB + `clip-ViT-B-32` ≈ 340 MB = ~810 MB
- Embedding cache (100K entries at full capacity): ~150 MB
- LanceDB working set: ~1–2 GB
- Python overhead: ~200 MB
- **Total baseline**: ~3 GB. 4 GB minimum, 8 GB comfortable.

**Disk sizing**: LanceDB storage ≈ `N_vectors × 0.0023` MB. For example:
- 1M vectors → ~2.3 GB
- 10M vectors → ~23 GB
- 100M vectors → ~230 GB

The 1.5× overhead accounts for IVF-PQ index structures. Provision 50% headroom above your expected vector count.

**First run**: ML models are downloaded from HuggingFace (~1 GB total). Requires internet access and patience (60–120 seconds).

### Software

- **Docker** + Docker Compose (recommended) — simplest deployment
- **Python 3.11+** (alternative) — `pip install -r requirements.txt`
- **Linux** (Ubuntu 22.04+ or Debian 12+ recommended). macOS works for testing.

### Network

| Port | Protocol | Required | Purpose |
|------|----------|----------|---------|
| `PORT` (8000) | TCP | **Yes** | HTTP API — search, index, P2P handshake |

**Only one TCP port.** Search-node uses HTTP REST for all communication — no UDP, no gRPC. This makes firewall setup simpler than any other Feedo microservice.

### Dependencies

A running **storage-node** is required. The search-node's PubSub crawler subscribes to `ws://{storage-node}/api/v1/pubsub/subscribe/feedo_new_events` to receive new content for indexing. Set `STORAGE_NODE_URL` to a reachable storage-node, and `GATEWAYS` to one or more storage-node addresses for failover.

---

## 2. Quick Start (Docker)

### Step 1: Create `.env` file

```bash
# === Search Node ===
PORT=8000
LANCE_DB_PATH=/data/feedo/search/lancedb_data

# === Storage (REQUIRED) ===
STORAGE_NODE_URL=http://storage-node:8040
GATEWAYS=storage-node:8040

# === P2P (start empty for genesis node) ===
KNOWN_PEERS=
PUBLIC_API_URL=http://your-public-ip:8000

# === Semantic Sharding (Phase 1.5) ===
SEMANTIC_SHARDING_ENABLED=true
EVENT_DRIVEN_CENTROIDS=true
```

### Step 2: Start the node

```bash
docker-compose -f docker-compose.search.yml up -d
```

### Step 3: Verify it's running

**Wait 60–120 seconds** for ML models to download and load (first run only). Then:

```bash
# Check node statistics
curl http://localhost:8000/explorer/stats
# → {"active_nodes": 1, "indexed_posts": 0, "network_health": "Syncing"}

# Check peers
curl http://localhost:8000/v1/node/peers
# → {"peers": []}

# Check logs for successful startup
docker-compose logs -f feedo-search | grep -E "Loading ML model|Uvicorn running|Semantic sharding"
```

You should see:
```
[SEARCH] Loading ML model (intfloat/multilingual-e5-small) via SentenceTransformers...
[SEARCH] Loading Multimodal model (clip-ViT-B-32)...
[SEARCH] ThreadPoolExecutor with N workers
[SEARCH] Semantic sharding: ENABLED (centroid_cache_ttl=600s, update_threshold=100)
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Step 4: Test search

```bash
# Search for anything — empty index is normal for a fresh node
curl "http://localhost:8000/query?text=test&limit=5"
# → {"results": []}

# Index a test document
curl -X POST http://localhost:8000/index_document \
  -H "Content-Type: application/json" \
  -d '{"hash_id":"test-doc-001","text":"Feedo search node operator quick start guide"}'
# → {"status": "ok"}

# Search for it
curl "http://localhost:8000/query?text=Feedo+search+guide&limit=5"
# → Should find the document
```

---

## 3. Running from Source

### Install Python and dependencies

```bash
# Ubuntu/Debian
sudo apt install python3 python3-pip libgomp1

# Verify Python version (3.11+ required)
python3 --version

# Install Python packages
cd microservices/search-node
pip install -r requirements.txt
```

### Run directly

```bash
export PORT=8000
export LANCE_DB_PATH=/data/feedo/search/lancedb_data
export STORAGE_NODE_URL=http://storage-node:8040
export GATEWAYS=storage-node:8040
export KNOWN_PEERS=""
export SEMANTIC_SHARDING_ENABLED=true

python3 main.py
```

First run downloads ML models (~1 GB) from HuggingFace. Subsequent runs load cached models in ~30 seconds.

### systemd unit file (production)

Create `/etc/systemd/system/feedo-search.service`:

```ini
[Unit]
Description=Feedo Search Node
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=feedo
WorkingDirectory=/opt/feedo/search
EnvironmentFile=/opt/feedo/search/.env
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now feedo-search
sudo journalctl -u feedo-search -f
```

---

## 4. Configuration Reference

All configuration via environment variables. Set these in your `.env` file or Docker Compose `environment` section.

### Server

| Variable | Type | Default | When to change |
|----------|------|---------|----------------|
| `PORT` | int | `8000` | If port 8000 is already in use |
| `HOST` | str | `127.0.0.1` | Set to `0.0.0.0` to listen on all interfaces (Docker does this automatically) |
| `LANCE_DB_PATH` | path | `./lancedb_data` | Point to a dedicated SSD mount, e.g. `/data/feedo/search/lancedb_data` |

### Storage & Gateways (REQUIRED)

| Variable | Type | Default | When to change |
|----------|------|---------|----------------|
| `STORAGE_NODE_URL` | str | `http://127.0.0.1:8040` | **Always set** — points to a running storage-node for PubSub crawler and DHT text fetching |
| `GATEWAYS` | str | (from `STORAGE_NODE_URL`) | Comma-separated host:port pairs for failover. Example: `node1:8040,node2:8040` |

### P2P Networking

| Variable | Type | Default | When to change |
|----------|------|---------|----------------|
| `KNOWN_PEERS` | str | (empty) | Comma-separated peer URLs to join the network. Leave empty to start a new network. Example: `http://node1:8000,http://node2:8000` |
| `PUBLIC_API_URL` | str | `http://{HOST}:{PORT}` | Public-facing URL for self-identification in handshakes. Set if behind a reverse proxy or TLS. |

### Phase 1.5 — Semantic Sharding

| Variable | Type | Default | When to change |
|----------|------|---------|----------------|
| `SEMANTIC_SHARDING_ENABLED` | bool | `true` | Master switch. `false` = full replication (old behaviour, safe fallback). |
| `SHARD_CENTROID_CACHE_TTL` | int | `600` | Seconds before local centroid cache expires. Lower = more frequent recomputation. |
| `SHARD_CENTROID_UPDATE_THRESHOLD` | int | `100` | New vectors before centroid cache invalidation. Lower = more responsive, higher CPU. |
| `SHARD_FORWARD_TIMEOUT` | float | `5.0` | HTTP timeout (seconds) for vector forwarding to peers. Increase for slow networks. |
| `EVENT_DRIVEN_CENTROIDS` | bool | `true` | Check for centroid drift every 10 seconds. Disable to save CPU (only periodic every 10 min). |
| `CENTROID_CHANGE_THRESHOLD` | float | `0.9` | Minimum cosine similarity to skip event-driven broadcast. Higher = broadcast more often. |

### Legacy (Pinata)

| Variable | Type | Default | When to change |
|----------|------|---------|----------------|
| `PINATA_API_KEY` | str | (empty) | Only if using `/proxy/publish` (Pinata IPFS upload). Not needed for `/proxy/publish_feedo`. |
| `PINATA_SECRET_API_KEY` | str | (empty) | See above. |

**Important**: Search-node has **no cryptographic keys**. No `NODE_PRIVATE_KEY`, no `NODE_WALLET_ADDRESS`, no key generation step. Your node's identity is simply its HTTP URL (`PUBLIC_API_URL`). This means:
- No key backup needed
- No key rotation concerns
- No secrets manager required
- `.env` file is safe to store in plain text (except optional Pinata keys)

---

## 5. First Node vs Joining an Existing Network

### Starting a new network (genesis node)

Set `KNOWN_PEERS=` (empty). Your node creates a new search index and operates solo. It indexes all content locally until other nodes join.

With `SEMANTIC_SHARDING_ENABLED=true`, the node runs as a solo shard — `is_my_shard()` always returns `True` because `global_knowledge_map` is empty.

### Joining an existing network

Set `KNOWN_PEERS` to the HTTP URL of at least one existing search-node. **Format**: plain HTTP URL (not a libp2p multiaddr — search-node uses HTTP, not UDP).

```bash
# Single peer
KNOWN_PEERS=http://search-node-0:8000

# Multiple peers (recommended for redundancy)
KNOWN_PEERS=http://search-node-0:8000,http://search-node-1:8000
```

**How to find a peer URL**: Ask the operator of an existing search-node, or check its `/v1/node/peers` endpoint:

```bash
curl http://known-search-node:8000/v1/node/peers
# → {"peers": ["http://search-node-0:8000", "http://search-node-1:8000"]}
```

### What happens after joining

1. Your node sends a handshake to all `KNOWN_PEERS` (centroid broadcast)
2. Peers reply with their centroids → your `global_knowledge_map` is populated
3. **Peer Exchange**: each handshake response includes a list of all other peers the remote node knows about. Your node automatically adds any new ones — enabling automatic mesh discovery.
4. Within 10 minutes (or sooner with event-driven updates), your node computes its own centroids and broadcasts them
5. New vectors are now distributed across all nodes based on semantic sharding
6. Search queries are automatically federated to relevant shards

---

## 6. Semantic Sharding Operations

This section is unique to search-node — it replaces the committee/consensus concepts found in other Feedo nodes.

### How sharding works

Each search-node stores only a **semantic shard** — approximately 1/N of the global vector index, where N is the number of active nodes. KMeans centroids partition the embedding space into N regions. Documents about technology land on one node, cooking recipes on another.

**You don't need to configure shards** — the system is fully automatic:
1. Your node computes its local KMeans centroids from its existing vectors
2. It broadcasts these centroids to all known peers (`/p2p/handshake`)
3. When new content arrives, `is_my_shard()` decides: index locally or forward to the right peer
4. Search queries are routed to the top-K peers whose centroids are closest to the query

### Feature flags you should know

| Flag | Default | What it does |
|------|---------|-------------|
| `SEMANTIC_SHARDING_ENABLED=true` | `true` | Sharding active. Vectors are distributed across peers. |
| `SEMANTIC_SHARDING_ENABLED=false` | | Full replication. Every node stores 100% of the index. Safe fallback if sharding causes issues, but does not scale. |
| `EVENT_DRIVEN_CENTROIDS=true` | `true` | Check for centroid drift every 10 seconds. Broadcasts immediately if centroids changed significantly. |
| `EVENT_DRIVEN_CENTROIDS=false` | | Only periodic broadcast (every 10 minutes). Saves CPU but slower adaptation to new content. |

### What to expect at different scales

| Nodes | Index per node | Behaviour |
|-------|---------------|-----------|
| 1 | 100% | Solo mode — indexes everything. `network_health: "Syncing"`. |
| 3 | ~33% each | Sharding active. `network_health: "Healthy"`. |
| 10 | ~10% each | Well-distributed. Federated search routes to ~3-5 peers per query. |
| 50 | ~2% each | Near-linear scaling. Each query hits only the most relevant shards. |

### Adding a node to the cluster

1. Deploy the new node with `KNOWN_PEERS` pointing to 2+ existing nodes
2. Start the node
3. Within 10 minutes: node receives centroids from existing peers
4. Node computes its own centroids and broadcasts them
5. New vectors start being forwarded to this node for its shard
6. Existing vectors **stay on their current nodes** — no rebalancing of old data

### Removing a node

Stop the node (Docker: `docker-compose stop`, systemd: `sudo systemctl stop feedo-search`). Vectors on that node become unavailable. New content for that shard will be routed to the next-closest node. Over time, the remaining nodes' centroids adapt to cover the gap.

### Check sharding health

```bash
# How many nodes does my node know about?
curl http://localhost:8000/explorer/stats
# → {"active_nodes": 3, ...}

# Which peers am I connected to?
curl http://localhost:8000/v1/node/peers
# → {"peers": ["http://node1:8000", "http://node2:8000"]}

# Is my node sending centroids? (check logs)
docker logs feedo-search 2>&1 | grep "📡 Sent centroids"
# Should see periodic (every ~10 min) or event-driven broadcasts
```

---

## 7. Monitoring & Health Checks

### Built-in health endpoints

```bash
# Node statistics (always returns 200)
curl http://localhost:8000/explorer/stats
# → {"active_nodes": 3, "indexed_posts": 15234, "network_health": "Healthy"}

# Known peers
curl http://localhost:8000/v1/node/peers
# → {"peers": [...]}

# Quick search health check (returns 200 even with empty results)
curl "http://localhost:8000/query?text=health+check&limit=1"

# Latest indexed documents
curl "http://localhost:8000/documents?limit=5"
```

### Log-based health indicators

| Log message | What it means |
|-------------|--------------|
| `[SEARCH] Loading ML model...` | ML models loading — normal at startup (first run: ~60-120s, cached: ~30s) |
| `[SEARCH] Semantic sharding: ENABLED` | Sharding is active — vectors will be distributed |
| `INFO: Uvicorn running on http://0.0.0.0:8000` | HTTP server is ready — node can accept requests |
| `🚀 Starting Event-Driven Crawler` | PubSub crawler starting — will connect to storage-node |
| `✅ Connected to PubSub WebSocket` | Successfully subscribed to storage-node's new content feed |
| `📡 Sent centroids to {peer}` | Successfully broadcast centroids to a peer |
| `🔄 Centroid drift detected` | Event-driven update triggered — centroids changed significantly |
| `📤 Routed vector {hash} to {peer}` | Vector forwarded to another node (normal sharding behaviour) |
| `🔎 Got event via PubSub! Buffering: {hash}` | New content received from storage-node for indexing |

### Warning signs

| Symptom | Likely issue |
|---------|-------------|
| No `Uvicorn running` after 2+ minutes | ML models still downloading (first run) or `sentence-transformers` failed to load. Check internet connection. |
| `⚠️ WebSocket connection lost` (occasional) | Storage-node temporarily unreachable. Crawler will retry automatically. |
| `❌ WebSocket connection lost` (persistent) | All gateways unreachable. Check `STORAGE_NODE_URL` and `GATEWAYS`. |
| `⚠️ Federated search timed out after 2s` | Peer unreachable or slow. Normal occasional occurrence — results from other peers still returned. |
| No `📡 Sent centroids` for 15+ minutes | Either `KNOWN_PEERS` is empty, or no peers are reachable. Check `/v1/node/peers`. |
| `⚠️ Error computing centroids` | LanceDB table is empty — normal for brand new node with no indexed content yet. |
| HTTP 429 "Rate limit exceeded" | Too many requests. Default limits: 100 req/s for `/query`, 50 for `/index_document`. |
| `indexed_posts` not growing | PubSub crawler disconnected from storage-node. Check `STORAGE_NODE_URL`. |

### Prometheus / Grafana

Not yet built-in (planned for Phase 5). For now, use `curl` + cron for basic monitoring:

```bash
# Check node health every 5 minutes
*/5 * * * * curl -sf http://localhost:8000/explorer/stats | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['network_health']=='Healthy', f'Unhealthy: {d}'"

# Alert if peers drop below minimum
*/5 * * * * curl -s http://localhost:8000/v1/node/peers | python3 -c "import sys,json; peers=json.load(sys.stdin)['peers']; assert len(peers)>=1, 'No peers!'"
```

---

## 8. Storage Management

### Where data lives

| Path | Content | Safe to delete? |
|------|---------|-----------------|
| `{LANCE_DB_PATH}/` | LanceDB database — all vectors, metadata, and indexes | Yes, but you lose your local index |
| `{LANCE_DB_PATH}/post_vectors.lance/` | Main table — vectors (384-dim) + image vectors (512-dim) + metadata | **No** — this is your data |
| `~/.cache/torch/sentence_transformers/` | Cached ML models (HuggingFace download) | Yes — will re-download on next start |

**No `peer_key.bin`** — search-node has no cryptographic identity. This simplifies backup and migration significantly compared to consensus/storage nodes.

### Check database size

```bash
du -sh lancedb_data/
# Example output: 2.3G   lancedb_data/
```

### Backup

```bash
# Full backup of LanceDB data
cp -r lancedb_data/ ~/backups/lancedb_$(date +%Y%m%d)/

# Or with tar for compression
tar -czf ~/backups/lancedb_$(date +%Y%m%d).tar.gz lancedb_data/
```

LanceDB supports snapshot-based backup — you can copy the entire directory while the node is running (LanceDB uses immutable data files with append-only writes).

### Reset (factory reset)

```bash
# Stop the node
docker-compose -f docker-compose.search.yml stop
# Or: sudo systemctl stop feedo-search

# Remove database
rm -rf lancedb_data/

# Restart — node creates a fresh empty LanceDB
docker-compose -f docker-compose.search.yml up -d
```

After reset: your node starts with an empty index. Peers will see your centroids change (or disappear). New content will be indexed in your shard. Old vectors that were on your node are lost — peers may still have copies if `SEMANTIC_SHARDING_ENABLED` was `false` (full replication) before the reset.

### Migration to a new server

1. Stop the node on the old server
2. Copy `lancedb_data/` to the new server
3. Update `PUBLIC_API_URL` to the new server's address
4. Update `KNOWN_PEERS` on **other nodes** to point to the new address
5. Start the node on the new server

No key migration needed — your node's identity is just its URL.

---

## 9. Firewall Configuration

### Required: open TCP for HTTP API

```bash
# ufw (Ubuntu/Debian)
sudo ufw allow 8000/tcp
sudo ufw enable

# firewalld (RHEL/CentOS/Fedora)
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload

# iptables (generic)
sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT
sudo iptables-save > /etc/iptables/rules.v4
```

**Only one port needed**: TCP 8000. No UDP, no gRPC, no separate P2P port. This is simpler than any other Feedo microservice.

### DO NOT expose

Nothing else. Search-node only listens on one TCP port.

### Verify port is reachable

```bash
# From another machine
curl http://YOUR_SERVER_IP:8000/explorer/stats
# → Should return JSON

# Or with netcat
nc -z YOUR_SERVER_IP 8000 && echo "TCP OPEN" || echo "TCP CLOSED"
```

### Cloud provider firewall

If using a cloud provider (AWS, GCP, DigitalOcean, Hetzner), also open TCP port 8000 in the **security group / firewall rules** in the provider's console. No UDP rules needed.

### TLS termination (optional but recommended)

For production, place search-node behind nginx or Caddy with Let's Encrypt:

```bash
# Caddy example (simplest)
sudo apt install caddy
# Caddyfile:
# search-node.example.com {
#     reverse_proxy localhost:8000
# }
```

After setting up TLS, update `PUBLIC_API_URL=https://search-node.example.com` so peers use HTTPS when connecting to your node.

---

## 10. Troubleshooting

| Symptom | Likely cause | Solution |
|---------|-------------|----------|
| Node doesn't respond for 2+ minutes after start | ML models downloading on first run (~1 GB) | Wait. Check internet. Models are cached in `~/.cache/torch/sentence_transformers/` after first download. |
| `ModuleNotFoundError: No module named 'sentence_transformers'` | Dependencies not installed | `pip install -r requirements.txt`. Also: `apt install libgomp1`. |
| `⚠️ WebSocket connection lost` (appears occasionally) | Storage-node temporarily unreachable | Normal — crawler will retry with next gateway. If persistent, check `STORAGE_NODE_URL`. |
| `❌ WebSocket connection lost` (repeating, never connects) | All gateways unreachable | Check `GATEWAYS`. Verify storage-node is running: `curl {STORAGE_URL}/api/files/recent`. Add more gateways for failover. |
| Search doesn't find recently published content | Content not yet indexed | Wait 3–5 seconds after publish. Check `/explorer/stats` — `indexed_posts` should be increasing. |
| HTTP 429 "Rate limit exceeded" | Too many requests | Reduce request rate. Defaults: `/query` 100 req/s, `/index_document` 50 req/s, `/p2p/*` 200 req/s. |
| High CPU usage (constant >80%) | ML inference on CPU | Normal under heavy query/indexing load. Add more vCPUs. For production scale, GPU inference (Phase 3). |
| `pip install` fails with `error: externally-managed-environment` | System Python on Ubuntu 24.04+ | Use a virtual environment: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`. Or use Docker. |
| `import torch` fails or segfault | Missing system library | `apt install libgomp1`. This is required by `sentence-transformers`. |
| `lancedb` "table not found" or IO errors | Corrupt database | Stop node, delete `LANCE_DB_PATH`, restart. Index will rebuild from new content. |
| Peers can't connect to my node | Wrong `PUBLIC_API_URL` or firewall | `PUBLIC_API_URL` must be the URL peers can reach. Not `localhost`. Check firewall: `curl http://YOUR_IP:8000/explorer/stats` from another machine. |
| `federated search timed out` for every query | All peers unreachable or slow | Check network connectivity to peers. Check `SHARD_FORWARD_TIMEOUT` — increase for slow networks. |
| Node uses too much RAM (>8 GB) | Embedding cache full + many concurrent queries | Reduce `max_emb_cache` in code (default 100K). Reduce `ThreadPoolExecutor` workers. Add more RAM. |

### Gathering debug info

```bash
# Check if HTTP API is responding
curl -v http://localhost:8000/explorer/stats

# Check peer connectivity
curl http://localhost:8000/v1/node/peers

# Check recent logs (Docker)
docker logs --tail 100 feedo-search 2>&1

# Check recent logs (systemd)
journalctl -u feedo-search --since "10 min ago" --no-pager

# Check LanceDB size and health
du -sh lancedb_data/
ls -la lancedb_data/

# Check if storage-node is reachable
curl -s http://storage-node:8040/api/files/recent || echo "Storage-node unreachable"

# Check Python version and installed packages
python3 --version
pip list | grep -E "fastapi|uvicorn|lancedb|sentence-transformers"

# Check open ports
ss -tln | grep 8000
```

---

## 11. Upgrading

### Docker

```bash
# Pull latest image
docker pull feedo-search-node:latest

# Restart
docker-compose -f docker-compose.search.yml up -d

# Wait for ML models to load (30-120s depending on cache)
sleep 30

# Verify
curl http://localhost:8000/explorer/stats
curl "http://localhost:8000/query?text=test&limit=1"
```

### From source

```bash
cd /opt/feedo
git pull
cd microservices/search-node
pip install -r requirements.txt
sudo systemctl restart feedo-search
sudo journalctl -u feedo-search -f
```

### Before upgrading

1. **Back up LanceDB data**: `cp -r lancedb_data/ ~/backups/lancedb_pre_upgrade_$(date +%Y%m%d)/`
2. **Check current version**: `grep 'Version' SEARCH_DOCS.md`
3. **Review release notes**: check commit history for breaking changes or new env vars
4. **Plan for 2–3 minutes downtime** (ML model warmup: 30s cached, 120s first run)
5. **Test after upgrade**: run a search query to verify functionality

### Compatibility notes

| Change | Backward compatible? |
|--------|---------------------|
| Phase 1.5: semantic sharding (v0.2.0) | ✅ Yes — `SEMANTIC_SHARDING_ENABLED=false` restores old full-replication behaviour |
| New env vars (sharding config) | ✅ Yes — all have sensible defaults; node works without setting them |
| LanceDB schema | ✅ Yes — v0.1.0 and v0.2.0 share identical schema (13 columns, 384-dim + 512-dim vectors) |
| Future: Fine-tuned model (Phase 2) | ✅ Yes — model loaded from separate path; LanceDB unchanged; fallback to base model |
| Future: GPU inference (Phase 3) | ✅ Yes — separate container; search-node falls back to CPU if GPU unavailable |
| Future: Real-time federation (Phase 4) | ✅ Yes — new endpoints, old endpoints unchanged |
| Future: Prometheus metrics (Phase 5) | ✅ Yes — new `/metrics` endpoint, existing endpoints unchanged |

### Rollback

```bash
# Docker
docker pull feedo-search-node:<previous-tag>
docker tag feedo-search-node:<previous-tag> feedo-search-node:latest
docker-compose -f docker-compose.search.yml up -d

# From source
cd /opt/feedo
git checkout <previous-commit-sha>
cd microservices/search-node
pip install -r requirements.txt
sudo systemctl restart feedo-search
```

---

## Additional Resources

- [SEARCH_DOCS.md](./SEARCH_DOCS.md) — Architecture, API reference, protocol details (for developers)
- [SEARCH_DEPLOY.md](./SEARCH_DEPLOY.md) — Production deployment guide (Docker Compose, K8s, Terraform, CI/CD)
- [SEARCH_ROADMAP.md](./SEARCH_ROADMAP.md) — 6-phase scaling plan
- [Main project README](../../README.md) — Feedo ecosystem overview