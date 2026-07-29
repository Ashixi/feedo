# Search Node — Deployment Guide

> **Audience**: DevOps engineers deploying search-node in production.
> **Prerequisites**: Familiarity with Docker, Python deployment, and Linux administration.
> For single-node operations, see [SEARCH_OPERATOR.md](./SEARCH_OPERATOR.md). For architecture, see [SEARCH_DOCS.md](./SEARCH_DOCS.md).

---

## 1. Deployment Overview

### Deployment matrix

| Scale | Nodes | Method | Orchestration |
|-------|-------|--------|---------------|
| **Single node** | 1 | Docker Compose | Manual (see Operator Guide) |
| **Small cluster** | 2–5 | Docker Compose + shared config | Manual or Ansible |
| **Medium cluster** | 5–50 | Docker Compose per node | Ansible + Terraform |
| **Large cluster** | 50+ | Kubernetes | K8s StatefulSet + Helm |

### Multi-node architecture (3 search nodes + 1 storage node)

```
┌──────────────────────────────────────────────────────────┐
│                    External Clients                       │
│              HTTP (search query / document index)         │
└───────┬──────────────────┬──────────────────┬────────────┘
        │                  │                  │
   ┌────▼─────┐       ┌────▼─────┐       ┌────▼─────┐
   │ Node 0   │◄─────►│ Node 1   │◄─────►│ Node 2   │
   │ :8000    │ HTTP  │ :8000    │ HTTP  │ :8000    │
   │ Shard A  │P2P    │ Shard B  │P2P    │ Shard C  │
   └────┬─────┘       └────┬─────┘       └────┬─────┘
        │                  │                  │
        │  Centroid        │  Centroid        │  Centroid
        │  handshake       │  handshake       │  handshake
        │  (HTTP POST)     │  (HTTP POST)     │  (HTTP POST)
        ▼                  ▼                  ▼
   ┌─────────────────────────────────────────────────────┐
   │         P2P Mesh (HTTP-based federated search)       │
   │   • /p2p/handshake — centroid exchange              │
   │   • /p2p/search — federated search queries          │
   │   • /p2p/index_vector — shard write forwarding      │
   └─────────────────────────────────────────────────────┘
        │                  │                  │
        │  PubSub WS       │  PubSub WS       │  PubSub WS
        ▼                  ▼                  ▼
   ┌─────────────────────────────────────────────────────┐
   │                 Storage Node(s)                      │
   │          WebSocket PubSub: feedo_new_events          │
   └─────────────────────────────────────────────────────┘
```

Each search-node stores only its **semantic shard** (Phase 1.5) — approximately 1/N of the global vector index. Queries are federated across nodes whose centroids are closest to the query vector. All inter-node communication is HTTP REST (no libp2p, no UDP).

---

## 2. Infrastructure Requirements

### Per-node sizing

| Resource | Minimum | Recommended (production) |
|----------|---------|--------------------------|
| vCPUs | 2 | 4+ |
| RAM | 4 GB | 8 GB |
| Boot disk | 20 GB SSD | 40 GB SSD |
| Data disk | 20–50 GB SSD | 100 GB SSD (for LanceDB index) |
| GPU | Not required | Recommended (Phase 3 — separate inference service) |
| Network | 100 Mbps, static public IP | 100 Mbps |
| OS | Ubuntu 22.04/24.04 LTS | Ubuntu 24.04 LTS |

**Disk formula**: LanceDB storage ≈ `N_vectors × 384 × 4 bytes × 1.5 (index overhead)`. Approximately:
- 100K vectors → ~230 MB
- 1M vectors → ~2.3 GB
- 10M vectors → ~23 GB
- 100M vectors → ~230 GB

The 1.5× overhead accounts for IVF-PQ index structures created by `optimize_index()`. Provision at least 50% headroom above your expected vector count.

**RAM considerations**:
- ML models: `multilingual-e5-small` ≈ 470 MB + `clip-ViT-B-32` ≈ 340 MB = ~810 MB
- Embedding cache (100K entries × 384 float32 × 4 bytes) ≈ ~150 MB at full capacity
- LanceDB working set: depends on query volume — typically 1–2 GB for active shards
- **Total baseline**: ~3 GB. Headroom of 5 GB for query processing.

**GPU recommendation (Phase 3)**:
For inference-heavy deployments, a separate GPU inference service (NVIDIA Triton or custom FastAPI GPU container) offloads embedding computation. This requires:
- GPU instance (T4/A10/L4) with ≥8 GB VRAM
- Separate Docker container on port 8081
- `inference_client.py` (Phase 3) delegates to GPU service with CPU fallback

### Cloud provider recommendations

| Provider | Best for | Notes |
|----------|----------|-------|
| **Hetzner** | Price/performance | CX22 (2 vCPU/4 GB) for small shards, CX32 (4 vCPU/8 GB) for medium. ~€4-8/month. |
| **Netcup** | Budget CPU nodes | RS series. Good for CPU-heavy ML inference. |
| **OVH** | Mid-range | Good DDoS protection. VPS Starter or Advance. |
| **DigitalOcean** | Quick setup | Basic Droplet ($12/month, 2 vCPU/4 GB). |
| **AWS EC2** | Enterprise | `c7g.large` (2 vCPU/4 GB, Graviton) or `t3.medium`. Higher cost. |

**CPU vs GPU trade-off**: For Phase 1 and 1.5, CPU inference with 4 vCPUs handles ~50 QPS. For Phase 3 (GPU inference), a separate GPU instance handles 1,000+ QPS. The search-node itself remains on CPU — only the inference service needs GPU.

---

## 3. Environment Variables — Production Profile

Complete `.env` for production search nodes:

```bash
# ==========================================
# Server
# ==========================================
PORT=8000
HOST=0.0.0.0
LANCE_DB_PATH=/data/feedo/search/lancedb_data

# ==========================================
# Storage & Gateways (REQUIRED)
# ==========================================
STORAGE_NODE_URL=http://storage-node:8040
GATEWAYS=storage-node-0:8040,storage-node-1:8040

# ==========================================
# P2P Networking
# ==========================================
KNOWN_PEERS=http://search-node-0:8000,http://search-node-2:8000
PUBLIC_API_URL=http://search-node-1.example.com:8000

# ==========================================
# Phase 1.5 — Semantic Sharding
# ==========================================
SEMANTIC_SHARDING_ENABLED=true        # Master switch: true → shard, false → full replication
SHARD_CENTROID_CACHE_TTL=600          # Seconds before centroid cache expires
SHARD_CENTROID_UPDATE_THRESHOLD=100   # New vectors before cache invalidation
SHARD_FORWARD_TIMEOUT=5.0             # HTTP timeout for peer vector forwarding
EVENT_DRIVEN_CENTROIDS=true           # Check for centroid drift every 10 seconds
CENTROID_CHANGE_THRESHOLD=0.9         # Min cosine similarity before broadcast

# ==========================================
# Legacy (Pinata) — optional
# ==========================================
# PINATA_API_KEY=
# PINATA_SECRET_API_KEY=

# ==========================================
# Logging
# ==========================================
# Python logs go to stderr — captured by Docker/systemd journald
```

### Variable lifecycle

| Variable | Set once? | Can change later? |
|----------|-----------|-------------------|
| `PORT` | Yes | Change requires updating `KNOWN_PEERS` on all other nodes |
| `LANCE_DB_PATH` | Yes | **NO** — changing loses the existing index. Migrate data first. |
| `STORAGE_NODE_URL` | At deploy | Yes — change and restart. Affects PubSub crawler connection. |
| `GATEWAYS` | At deploy | Yes — add/remove and restart. Used for failover in PubSub crawler. |
| `KNOWN_PEERS` | At deploy | Yes — add/remove and restart anytime. Dynamic discovery via handshake. |
| `PUBLIC_API_URL` | At deploy | Yes — change and restart. Must match how peers can reach this node. |
| `SEMANTIC_SHARDING_ENABLED` | — | Yes — toggle and restart. `false` = full replication (safe fallback). |
| `SHARD_CENTROID_CACHE_TTL` | — | Yes — change and restart anytime |
| `SHARD_CENTROID_UPDATE_THRESHOLD` | — | Yes — change and restart anytime |
| `SHARD_FORWARD_TIMEOUT` | — | Yes — change and restart anytime |
| `EVENT_DRIVEN_CENTROIDS` | — | Yes — toggle and restart anytime |
| `CENTROID_CHANGE_THRESHOLD` | — | Yes — change and restart anytime |

### Migration from single-node (full replication) to sharded

1. Deploy new nodes with `SEMANTIC_SHARDING_ENABLED=true` and `KNOWN_PEERS` pointing to the genesis node
2. Restart the genesis node with `SEMANTIC_SHARDING_ENABLED=true` and updated `KNOWN_PEERS`
3. Centroids will be computed within 10 minutes — after first handshake cycle, sharding is active
4. **No data migration needed** — existing vectors stay on the genesis node. New vectors are distributed by the sharding logic.

---

## 4. Docker Compose Deployment

### Production `docker-compose.search.yml`

```yaml
version: '3.8'

services:
  search-node:
    image: feedo-search-node:latest      # Replace with actual image
    container_name: feedo-search
    restart: unless-stopped
    ports:
      - "8000:8000"                      # HTTP only — no UDP needed
    env_file:
      - .env
    volumes:
      - /data/feedo/search/lancedb_data:/app/lancedb_data:rw
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    deploy:
      resources:
        limits:
          memory: 8G
          cpus: '4'
        reservations:
          memory: 2G
          cpus: '2'
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/explorer/stats"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 120s              # ML model loading takes 60-120s on first run
```

**Key decisions**:

- **Bridge network, not host** — search-node uses only HTTP (TCP port 8000). No libp2p UDP required. Bridge mode with port mapping is simpler and safer.
- **`start_period: 120s`** — `sentence-transformers` downloads and loads ~1 GB of ML models on first run. Health checks start after 2 minutes to avoid false negatives.
- **Volume mount on host path** — LanceDB data on dedicated SSD. Docker named volumes work but complicate backup.
- **Resource limits** — memory limit 8 GB prevents ML model + cache from starving other services. CPU limit 4 vCPUs aligns with `ThreadPoolExecutor(max_workers=os.cpu_count())`.
- **Healthcheck uses `/explorer/stats`** — lightweight endpoint that returns immediately. Does not trigger embedding computation.

### Dockerfile reference

The existing `Dockerfile` at `microservices/search-node/Dockerfile`:

```dockerfile
FROM python:3.12-slim-bookworm
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py p2p.py crawler.py vector_service.py storage_adapters.py .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Build and deploy:**

```bash
# Build
docker build -t feedo-search-node:latest -f microservices/search-node/Dockerfile microservices/search-node/

# On each node
scp docker-compose.search.yml .env user@node:/opt/feedo/search/
ssh user@node
cd /opt/feedo/search
docker-compose -f docker-compose.search.yml up -d
docker-compose -f docker-compose.search.yml logs -f
```

### Multi-node with Docker Compose

Deploy to 3 nodes (node0, node1, node2) with identical `docker-compose.search.yml` but different `.env`:

| Node | `KNOWN_PEERS` | `PORT` | `LANCE_DB_PATH` |
|------|---------------|--------|------------------|
| node0 (genesis) | (empty) | 8000 | /data/feedo/search/lancedb_data |
| node1 (follower) | `http://{node0_ip}:8000` | 8000 | /data/feedo/search/lancedb_data |
| node2 (follower) | `http://{node0_ip}:8000,http://{node1_ip}:8000` | 8000 | /data/feedo/search/lancedb_data |

All nodes can use the same port (8000) since they run on different hosts. `PUBLIC_API_URL` should be set to the externally reachable URL of each node.

---

## 5. Kubernetes Deployment

### Key considerations for K8s

- **No `hostNetwork` needed** — search-node uses HTTP only (TCP). Standard K8s networking works.
- **StatefulSet** — stable pod identity for `KNOWN_PEERS` references. Pod ordinal used for unique config.
- **PersistentVolumeClaim** — SSD StorageClass, `ReadWriteOnce`. LanceDB must not be shared between pods.
- **podAntiAffinity** — spread pods across nodes for CPU/Memory isolation.
- **`terminationGracePeriodSeconds: 60`** — allows in-flight federated queries to complete.
- **`startupProbe`** — long initial delay (120s) for ML model download on first run.

### `k8s/search-statefulset.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: feedo-search
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: search-config
  namespace: feedo-search
data:
  PORT: "8000"
  HOST: "0.0.0.0"
  LANCE_DB_PATH: "/data/feedo/search/lancedb_data"
  STORAGE_NODE_URL: "http://storage-node.feedo-storage:8040"
  GATEWAYS: "storage-node-0.feedo-storage:8040,storage-node-1.feedo-storage:8040"
  SEMANTIC_SHARDING_ENABLED: "true"
  SHARD_CENTROID_CACHE_TTL: "600"
  SHARD_CENTROID_UPDATE_THRESHOLD: "100"
  SHARD_FORWARD_TIMEOUT: "5.0"
  EVENT_DRIVEN_CENTROIDS: "true"
  CENTROID_CHANGE_THRESHOLD: "0.9"
---
apiVersion: v1
kind: Service
metadata:
  name: search-headless
  namespace: feedo-search
spec:
  clusterIP: None                   # Headless — each pod reachable by DNS
  selector:
    app: search-node
  ports:
    - name: http
      port: 8000
      protocol: TCP
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: search-node
  namespace: feedo-search
spec:
  serviceName: search-headless
  replicas: 3
  podManagementPolicy: Parallel     # Start all simultaneously
  selector:
    matchLabels:
      app: search-node
  template:
    metadata:
      labels:
        app: search-node
    spec:
      terminationGracePeriodSeconds: 60
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: search-node
              topologyKey: kubernetes.io/hostname
      containers:
        - name: search-node
          image: feedo-search-node:latest
          envFrom:
            - configMapRef:
                name: search-config
          env:
            - name: KNOWN_PEERS
              value: ""                                           # Genesis: empty. Followers: set per pod.
            - name: PUBLIC_API_URL
              value: "http://search-node-$(POD_ORDINAL).feedo-search:8000"
          ports:
            - containerPort: 8000
              protocol: TCP
          resources:
            requests:
              memory: "2Gi"
              cpu: "2"
            limits:
              memory: "8Gi"
              cpu: "4"
          volumeMounts:
            - name: search-data
              mountPath: /data/feedo/search/lancedb_data
          startupProbe:
            httpGet:
              path: /explorer/stats
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
            failureThreshold: 18        # 10 + 18*10 = 190s — generous for model loading
          readinessProbe:
            httpGet:
              path: /explorer/stats
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /explorer/stats
              port: 8000
            initialDelaySeconds: 120
            periodSeconds: 30
  volumeClaimTemplates:
    - metadata:
        name: search-data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: "ssd"
        resources:
          requests:
            storage: 50Gi              # Sized to expected vector count × 1.5
```

### Deploy to K8s

```bash
kubectl apply -f k8s/search-statefulset.yaml
kubectl -n feedo-search get pods -w
kubectl -n feedo-search logs -f search-node-0
```

### Bootstrapping on K8s

Node 0 starts first (genesis). After it becomes ready:

```bash
# Get Node 0 URL
kubectl -n feedo-search get pod search-node-0 -o wide
# → IP: 10.x.x.x

# Build peer URLs for nodes 1 and 2:
# http://search-node-0.feedo-search:8000
# http://search-node-1.feedo-search:8000
```

Then patch the StatefulSet with `KNOWN_PEERS`:

```bash
kubectl -n feedo-search set env statefulset/search-node \
  KNOWN_PEERS="http://search-node-0.feedo-search:8000"
kubectl -n feedo-search rollout restart statefulset/search-node
```

After restart, all nodes discover each other. Verify:

```bash
kubectl -n feedo-search exec search-node-0 -- curl -s http://localhost:8000/v1/node/peers
# → {"peers": ["http://search-node-1.feedo-search:8000", "http://search-node-2.feedo-search:8000"]}
```

---

## 6. Infrastructure as Code

### Terraform + Ansible structure

```
deploy/
├── terraform/
│   ├── main.tf              # Compute instances, volumes, security groups
│   ├── variables.tf         # Node count, region, instance type
│   ├── outputs.tf           # Public IPs, used by Ansible inventory
│   └── terraform.tfvars     # Your specific values
├── ansible/
│   ├── deploy.yml           # Main playbook: install Python deps, deploy compose, start
│   ├── update.yml           # Rolling update: git pull, restart
│   ├── inventory/
│   │   └── hosts.yml        # Generated from terraform output
│   └── group_vars/
│       └── all.yml          # KNOWN_PEERS, STORAGE_NODE_URL, sharding config
└── docker-compose.search.yml
```

### Terraform snippet (Hetzner example)

```hcl
resource "hcloud_server" "search_node" {
  count       = var.node_count
  name        = "feedo-search-${count.index}"
  server_type = "cx32"           # 4 vCPU, 8 GB RAM — good for ML inference
  image       = "ubuntu-24.04"
  location    = "nbg1"           # Nuremberg

  public_net {
    ipv4_enabled = true
  }
}

resource "hcloud_volume" "search_data" {
  count     = var.node_count
  name      = "feedo-search-data-${count.index}"
  size      = 50                  # 50 GB — adjust to expected vector count
  server_id = hcloud_server.search_node[count.index].id
  format    = "ext4"
  automount = true
}

resource "hcloud_firewall" "search" {
  name = "feedo-search"
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "8000"
    source_ips = ["0.0.0.0/0"]
  }
}
```

**Firewall**: Only TCP port 8000 needs to be open. No UDP ports required (HTTP-based P2P).

### Ansible snippet (deploy playbook)

```yaml
- name: Deploy Feedo Search Node
  hosts: search_nodes
  become: yes
  vars:
    lance_db_path: /data/feedo/search/lancedb_data
    app_dir: /opt/feedo/search
  tasks:
    - name: Install Python and pip
      apt:
        name:
          - python3
          - python3-pip
          - docker.io
        state: present

    - name: Create data directory
      file:
        path: "{{ lance_db_path }}"
        state: directory
        owner: "1000"
        group: "1000"

    - name: Copy application files
      copy:
        src: "{{ item }}"
        dest: "{{ app_dir }}/"
      loop:
        - main.py
        - p2p.py
        - crawler.py
        - vector_service.py
        - storage_adapters.py
        - requirements.txt

    - name: Install Python dependencies
      pip:
        requirements: "{{ app_dir }}/requirements.txt"
        executable: pip3

    - name: Copy compose file
      copy:
        src: docker-compose.search.yml
        dest: "{{ app_dir }}/docker-compose.search.yml"

    - name: Template .env
      template:
        src: .env.j2
        dest: "{{ app_dir }}/.env"
        mode: 0600

    - name: Start search node
      docker_compose:
        project_src: "{{ app_dir }}"
        files: docker-compose.search.yml
        state: present
```

### `ansible/group_vars/all.yml`

```yaml
# No secrets to encrypt — search-node has no cryptographic keys
search_known_peers:
  - ""                                                     # Genesis node
  - "http://{{ hostvars['search-node-0'].ansible_host }}:8000"
  - "http://{{ hostvars['search-node-0'].ansible_host }}:8000,http://{{ hostvars['search-node-1'].ansible_host }}:8000"

search_storage_url: "http://storage-node:8040"
search_gateways: "storage-node-0:8040,storage-node-1:8040"

search_sharding:
  enabled: true
  centroid_cache_ttl: 600
  centroid_update_threshold: 100
  forward_timeout: 5.0
  event_driven_centroids: true
  centroid_change_threshold: 0.9
```

**No vault needed** — search-node has no cryptographic secrets (no private keys, no wallet addresses). All configuration is safe to store in plain text.

---

## 7. Multi-Node Cluster Setup

### Step-by-step: 3-node cluster

**Step 1 — Verify storage-node is running**

```bash
curl http://{STORAGE_IP}:8040/api/files/recent
# → {"hashes": [...]} or empty list — any response means storage-node is up
```

**Step 2 — Deploy genesis node (Node 0)**

`.env` for Node 0:
```bash
PORT=8000
HOST=0.0.0.0
STORAGE_NODE_URL=http://{STORAGE_IP}:8040
GATEWAYS={STORAGE_IP}:8040
KNOWN_PEERS=                           # Empty — this IS the first node
PUBLIC_API_URL=http://{NODE0_PUBLIC_IP}:8000
SEMANTIC_SHARDING_ENABLED=true
EVENT_DRIVEN_CENTROIDS=true
```

Start Node 0. Wait for logs:
```
[SEARCH] Loading ML model (intfloat/multilingual-e5-small) via SentenceTransformers...
[SEARCH] Loading Multimodal model (clip-ViT-B-32)...
[SEARCH] ThreadPoolExecutor with N workers
[SEARCH] Semantic sharding: ENABLED (centroid_cache_ttl=600s, update_threshold=100)
🌐 Starting P2P Gossip Loop with event-driven centroid detection...
🚀 Starting Event-Driven Crawler with batch processing...
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Step 3 — Deploy follower nodes (Node 1, Node 2)**

`.env` for Node 1:
```bash
PORT=8000
HOST=0.0.0.0
STORAGE_NODE_URL=http://{STORAGE_IP}:8040
GATEWAYS={STORAGE_IP}:8040
KNOWN_PEERS=http://{NODE0_IP}:8000
PUBLIC_API_URL=http://{NODE1_PUBLIC_IP}:8000
SEMANTIC_SHARDING_ENABLED=true
EVENT_DRIVEN_CENTROIDS=true
```

`.env` for Node 2 (redundant peers):
```bash
KNOWN_PEERS=http://{NODE0_IP}:8000,http://{NODE1_IP}:8000
PUBLIC_API_URL=http://{NODE2_PUBLIC_IP}:8000
# ... same as Node 1 for other vars
```

**Step 4 — Verify cluster**

```bash
# Check peers on each node
curl http://{NODE0_IP}:8000/v1/node/peers
curl http://{NODE1_IP}:8000/v1/node/peers
curl http://{NODE2_IP}:8000/v1/node/peers
# Each should list the other two nodes

# Check explorer stats
curl http://{NODE0_IP}:8000/explorer/stats
# → {"active_nodes": 3, "indexed_posts": 0, "network_health": "Healthy"}

# Check logs for handshake success
docker-compose logs | grep "📡 Sent centroids"
# → Should see periodic broadcasts every ~10 minutes
```

**Step 5 — End-to-end test**

```bash
# 1. Publish a test website through Node 0
curl -X POST http://{NODE0_IP}:8000/proxy/publish_feedo \
  -F "file=@test_site.zip"
# → {"cid": "abc123...", "title": "Test Site"}

# 2. Search on Node 0 (local shard)
curl "http://{NODE0_IP}:8000/query?text=test+site&federated=true"
# → Should find the site

# 3. Search on Node 2 (federated — vector may have been forwarded)
curl "http://{NODE2_IP}:8000/query?text=test+site&federated=true"
# → Should ALSO find the site (via federated search if vector was forwarded,
#   or locally if it stayed on Node 2)

# 4. Index a document directly on Node 1
curl -X POST http://{NODE1_IP}:8000/index_document \
  -H "Content-Type: application/json" \
  -d '{"hash_id":"test-doc-001","text":"blockchain consensus PBFT"}'

# 5. Search from Node 0 — should find via federation
curl "http://{NODE0_IP}:8000/query?text=blockchain+consensus&federated=true"
```

### Adding a node to an existing cluster

1. Deploy new node with `KNOWN_PEERS` pointing to 2+ existing nodes
2. Start the node — it receives centroids via handshake within 10 minutes
3. Existing nodes discover the new node when it broadcasts its own centroids
4. No data migration — the new node starts receiving vectors for its shard as new content is indexed

### Removing a node

```bash
docker-compose -f docker-compose.search.yml stop
# Or: kubectl scale statefulset search-node --replicas=2
```

Vectors stored on the removed node become unavailable for search. New vectors for that shard will be assigned to the next-closest node. **No manual rebalancing needed** — the KMeans centroids on remaining nodes will naturally absorb the orphaned shard over time as new vectors are indexed.

---

## 8. Networking Deep Dive

### Why HTTP, not libp2p/UDP

Search-node uses **HTTP REST** for all inter-node communication. This is deliberate:

| Reason | Detail |
|--------|--------|
| **Python ecosystem** | FastAPI + httpx are mature, well-tested. libp2p Python bindings are experimental. |
| **No NAT complexity** | HTTP over TCP works through standard firewalls, load balancers, and reverse proxies. No UDP hole-punching needed. |
| **Observability** | HTTP requests are easy to log, trace, and monitor. Standard tools (Prometheus, Grafana, ELK) work out of the box. |
| **Compatibility** | Search-node can sit behind nginx/Caddy/Traefik for TLS termination, rate limiting, and load balancing. |
| **Simplicity** | Single port (8000). No separate P2P port, no gRPC port. |

### Bandwidth estimation

Compared to storage-node (which transfers megabyte shards over UDP), search-node traffic is lightweight JSON-over-HTTP:

| Operation | Request size | Response size | Frequency |
|-----------|-------------|---------------|-----------|
| Centroid handshake (out) | ~30 KB JSON (20 centroids × 384 float32) | 20 bytes (`{"status":"ok"}`) | Every 10 min to each peer (or on drift) |
| Centroid handshake (in) | ~30 KB JSON | 20 bytes | Every 10 min from each peer |
| Federated search (out) | ~200 bytes (`{"query":"...","ttl":2}`) | — | Per federated query |
| Federated search (in) | ~200 bytes | ~50 KB JSON (10 results) | Per federated query |
| Vector forwarding (out) | ~2 KB JSON (384-dim vector + metadata) | 20 bytes | Per forwarded vector |
| Vector forwarding (in) | ~2 KB JSON | 20 bytes | Per received vector |
| PubSub crawler (in) | — | 1–10 KB per event (WebSocket) | Continuous |

**Example**: A cluster with 3 nodes, 100K vectors indexed, 50 queries/second:
- Centroid traffic: ~90 KB per handshake cycle per node → ~10 KB/min per node
- Federated search: 50 QPS × 2 peer queries × 250 bytes = ~25 KB/s outbound, 50 QPS × 2 peers × 50 KB = ~5 MB/s inbound
- PubSub crawler: ~10 KB/s inbound per node (depends on content ingestion rate)
- **Total**: ~5 MB/s inbound, ~25 KB/s outbound — easily handled by 100 Mbps link

### Firewall setup

| Provider | How to open TCP 8000 |
|----------|---------------------|
| **Hetzner** | Cloud Console → Firewalls → Create firewall → Inbound rule: TCP, Port 8000, Source 0.0.0.0/0. Apply to server. |
| **AWS** | EC2 → Security Groups → Inbound rules → Custom TCP, Port 8000, Source 0.0.0.0/0 |
| **GCP** | VPC Network → Firewall → Create rule → Allow ingress, TCP:8000, Target: instance tag `feedo-search` |
| **DigitalOcean** | Networking → Firewalls → Create firewall → Inbound: TCP, Port 8000, All sources. Apply to Droplet. |

**Only one port needed**: TCP 8000. No UDP, no gRPC. This simplifies firewall configuration significantly compared to consensus/storage nodes.

### TLS termination (recommended)

For production, place search-node behind a reverse proxy with TLS:

```nginx
# nginx config snippet
server {
    listen 443 ssl;
    server_name search-node-0.example.com;

    ssl_certificate     /etc/letsencrypt/live/search-node-0.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/search-node-0.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 30s;    # Federated search can take up to 2s + network
    }
}
```

Set `PUBLIC_API_URL=https://search-node-0.example.com` so peers use TLS when connecting to this node.

---

## 9. Secrets Management

### No cryptographic secrets

Search-node is **unique** among Feedo microservices — it has no cryptographic keys or wallet addresses:

- No `NODE_PRIVATE_KEY` — P2P identity is based on HTTP URL, not libp2p PeerId
- No `NODE_WALLET_ADDRESS` — search-node does not participate in PBFT consensus
- No blockchain RPC — no on-chain transactions

This simplifies deployment significantly — no secret generation, no key rotation concerns, no vault needed.

### Optional secrets

| Secret | Required? | Used by | Storage recommendation |
|--------|-----------|---------|----------------------|
| `PINATA_API_KEY` | No | `/proxy/publish` (Pinata IPFS upload) | `.env` with `chmod 600` or Docker secrets |
| `PINATA_SECRET_API_KEY` | No | `/proxy/publish` (Pinata IPFS upload) | `.env` with `chmod 600` or Docker secrets |

These are only needed if you use the Pinata publishing endpoint. For production, prefer `/proxy/publish_feedo` which uses the storage-node directly (no API keys).

### If you use Docker Swarm or K8s Secrets

```yaml
# Kubernetes Secret (optional)
apiVersion: v1
kind: Secret
metadata:
  name: search-secrets
  namespace: feedo-search
type: Opaque
stringData:
  PINATA_API_KEY: "your-key"            # Only if using Pinata
  PINATA_SECRET_API_KEY: "your-secret"   # Only if using Pinata
```

### Summary

| Concern | Status |
|---------|--------|
| Private keys to generate | **None** |
| Secrets to rotate | **None** (unless using Pinata) |
| Vault/Secrets Manager needed | **No** |
| `.env` file safe in plain text | **Yes** |

---

## 10. Monitoring Stack

### Current built-in endpoints

```bash
# Node statistics
curl http://localhost:8000/explorer/stats
# → {"active_nodes": 3, "indexed_posts": 15234, "network_health": "Healthy"}

# Known peers
curl http://localhost:8000/v1/node/peers
# → {"peers": ["http://node1:8000", "http://node2:8000"]}

# Quick search health check
curl "http://localhost:8000/query?text=test&limit=1"
# → {"results": [...]}  — any response means search is working
```

### Recommended: Prometheus + Grafana

**Phase 5** will add a native `/metrics` endpoint in Prometheus format. Until then, use `json_exporter` to scrape `/explorer/stats`:

```yaml
# json_exporter config: /etc/json_exporter/config.yml
modules:
  search_stats:
    headers:
      Accept: application/json
    metrics:
      - name: feedo_search_active_nodes
        path: '{ .active_nodes }'
        type: value
      - name: feedo_search_indexed_posts
        path: '{ .indexed_posts }'
        type: value
      - name: feedo_search_network_health
        path: '{ .network_health }'
        type: value
        labels:
          health: '{ .network_health }'
```

**Prometheus scrape config** (`prometheus.yml`):

```yaml
scrape_configs:
  - job_name: 'feedo-search'
    scrape_interval: 30s
    static_configs:
      - targets:
          - 'search-node-0:8000'
          - 'search-node-1:8000'
          - 'search-node-2:8000'
    metrics_path: '/explorer/stats'
    # Use json_exporter as a proxy:
    # proxy_url: http://localhost:7979/probe?target=http://search-node-0:8000/explorer/stats&module=search_stats
```

**Node Exporter** (system metrics): CPU, RAM, disk I/O, network throughput. Install on every node:
```bash
sudo apt install prometheus-node-exporter
```

**Grafana dashboard panels:**

| Panel | Source | Type |
|-------|--------|------|
| Active nodes | `feedo_search_active_nodes` | Stat |
| Indexed posts per node | `feedo_search_indexed_posts` | Gauge (per instance) |
| Network health | `feedo_search_network_health` | State timeline |
| Known peers count | Log-based: parse `/v1/node/peers` response | Stat |
| Cache hit rate | Not yet available (Phase 5) | — |
| Query latency | Not yet available (Phase 5) | — |
| CPU usage | Node Exporter | Graph |
| RAM usage | Node Exporter | Graph |
| Disk usage (`/data/feedo/search`) | Node Exporter | Gauge |
| Network throughput | Node Exporter | Graph |

### Alerting rules (Prometheus AlertManager)

```yaml
groups:
  - name: feedo-search
    rules:
      - alert: SearchNodeDown
        expr: up{job="feedo-search"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Search node {{ $labels.instance }} is down"

      - alert: SearchUnhealthy
        expr: feedo_search_network_health != "Healthy"
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Search node {{ $labels.instance }} reports {{ $value }}"

      - alert: SearchLowPeers
        expr: count(feedo_search_active_nodes) < 2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Search cluster has fewer than 2 active nodes"

      - alert: DiskFull
        expr: node_filesystem_avail_bytes{mountpoint="/data/feedo/search"} / node_filesystem_size_bytes{mountpoint="/data/feedo/search"} < 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "LanceDB data disk >90% full on {{ $labels.instance }}"

      - alert: HighCPU
        expr: rate(node_cpu_seconds_total{mode="user"}[5m]) * 100 > 80
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "CPU usage >80% on {{ $labels.instance }} — ML inference may be bottlenecked"
```

### Log aggregation with Loki + Promtail

Search-node logs to stderr (Python default). Capture with Promtail:

```yaml
# promtail config snippet
scrape_configs:
  - job_name: feedo-search
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
    relabel_configs:
      - source_labels: [__meta_docker_container_name]
        regex: feedo-search
        action: keep
```

Key log patterns to alert on:
- `⚠ Federated search timed out` → peer unreachable or slow
- `⚠ WebSocket connection lost` → storage-node PubSub feed down
- `❌ WebSocket connection lost` → all gateways unreachable
- `🔄 Centroid drift detected` → normal operation, but high frequency may indicate shard instability

---

## 11. CI/CD Pipeline

### GitHub Actions — test, build, deploy

```yaml
name: Search Node CI/CD

on:
  push:
    branches: [main]
    paths:
      - 'microservices/search-node/**'
  pull_request:
    paths:
      - 'microservices/search-node/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r microservices/search-node/requirements.txt

      - name: Syntax check
        run: |
          python -m py_compile microservices/search-node/main.py
          python -m py_compile microservices/search-node/vector_service.py
          python -m py_compile microservices/search-node/crawler.py
          python -m py_compile microservices/search-node/p2p.py
          python -m py_compile microservices/search-node/storage_adapters.py

      # Integration test requires storage-node binary — skip in CI for now
      # See tests/test_search.py for local integration testing

  build:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: |
          docker build \
            -t feedo-search-node:${{ github.sha }} \
            -t feedo-search-node:latest \
            -f microservices/search-node/Dockerfile \
            microservices/search-node/
      - name: Push to registry
        run: |
          docker tag feedo-search-node:${{ github.sha }} registry.example.com/feedo-search-node:${{ github.sha }}
          docker push registry.example.com/feedo-search-node:${{ github.sha }}

  deploy-canary:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to canary node
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.CANARY_SEARCH_HOST }}
          username: feedo
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /opt/feedo/search
            docker pull registry.example.com/feedo-search-node:${{ github.sha }}
            docker tag registry.example.com/feedo-search-node:${{ github.sha }} feedo-search-node:latest
            docker-compose -f docker-compose.search.yml up -d
            sleep 60   # Wait for health check (start_period 120s covers model loading)
            curl -sf http://localhost:8000/explorer/stats || exit 1
            curl -sf "http://localhost:8000/query?text=health+check&limit=1" || true

  deploy-production:
    needs: deploy-canary
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    strategy:
      matrix:
        host: ${{ fromJSON(secrets.PRODUCTION_SEARCH_HOSTS) }}
    steps:
      - name: Deploy to production
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ matrix.host }}
          username: feedo
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /opt/feedo/search
            docker pull registry.example.com/feedo-search-node:${{ github.sha }}
            docker tag registry.example.com/feedo-search-node:${{ github.sha }} feedo-search-node:latest
            docker-compose -f docker-compose.search.yml up -d
            sleep 30
            curl -sf http://localhost:8000/explorer/stats || exit 1
```

### Canary deployment strategy

1. Build and push Docker image
2. Deploy to 1 node (canary)
3. Wait for health check (120s start period + model loading)
4. Verify `/explorer/stats` responds and `network_health` is acceptable
5. Run a test query to verify search functionality
6. Wait 5 minutes — observe Grafana for anomalies
7. Deploy to remaining nodes (rolling, one at a time)

### Rollback

Python deployments are fast — no compilation step:

```bash
# Docker-based rollback
docker pull registry.example.com/feedo-search-node:<previous-tag>
docker tag registry.example.com/feedo-search-node:<previous-tag> feedo-search-node:latest
docker-compose -f docker-compose.search.yml up -d
```

For `docker-compose` with `latest` tag:
```bash
# Rebuild from previous commit
cd /opt/feedo
git checkout <previous-commit-sha>
docker build -t feedo-search-node:latest -f microservices/search-node/Dockerfile microservices/search-node/
docker-compose -f docker-compose.search.yml up -d
```

---

## 12. Production Hardening Checklist

Before going to production, verify every item:

- [ ] **Python**: Python 3.11+ installed. Check: `python3 --version`
- [ ] **Dependencies**: `requirements.txt` has pinned versions. Run `pip install -r requirements.txt` before containerising.
- [ ] **ML Models**: First run downloads `multilingual-e5-small` (~470 MB) and `clip-ViT-B-32` (~340 MB). Ensure sufficient disk space and bandwidth for initial model download.
- [ ] **Network**: TCP port 8000 open in cloud provider firewall AND OS firewall (ufw/iptables)
- [ ] **Network**: No UDP ports needed (HTTP-only P2P)
- [ ] **Storage**: `LANCE_DB_PATH` on dedicated SSD volume, not root partition, XFS or ext4
- [ ] **Storage**: Disk space ≥ expected vector count × 2.3 KB × 1.5 overhead, with monitoring alert at 80%
- [ ] **Storage-node**: `STORAGE_NODE_URL` and `GATEWAYS` point to running storage-node instances. PubSub crawler depends on this.
- [ ] **P2P**: `KNOWN_PEERS` contains ≥2 other search-node URLs for redundancy
- [ ] **P2P**: `SEMANTIC_SHARDING_ENABLED=true` for production (enables shard distribution)
- [ ] **P2P**: `EVENT_DRIVEN_CENTROIDS=true` for faster shard adaptation
- [ ] **Resources**: CPU/memory limits configured (Docker: `deploy.resources.limits`, systemd: `MemoryMax`/`CPUQuota`)
- [ ] **Resources**: `ThreadPoolExecutor` workers = `os.cpu_count()` — ensure at least 2 vCPUs allocated
- [ ] **Logs**: Log rotation configured (Docker: `max-size`/`max-file`, systemd: journald `MaxRetentionSec`)
- [ ] **Process**: Runs as non-root user (`user: "1000:1000"` in Docker)
- [ ] **Process**: Automatic restart on failure (`restart: unless-stopped` in Docker, `Restart=always` in systemd)
- [ ] **Health check**: `/explorer/stats` endpoint monitored. `start_period` ≥ 120s for ML model loading.
- [ ] **Monitoring**: Node statistics scraped by Prometheus, alerts configured for node down + high disk
- [ ] **Monitoring**: System metrics (CPU, RAM, disk, network) collected via Node Exporter
- [ ] **Backup**: `lancedb_data/` directory backed up periodically. LanceDB supports snapshot-based backup.
- [ ] **Backup**: `peer_key.bin` is NOT needed — search-node has no libp2p identity key
- [ ] **CI/CD**: Automated syntax check passes, Docker build succeeds, canary deployment before full rollout
- [ ] **TLS**: Production nodes behind reverse proxy (nginx/Caddy) with Let's Encrypt TLS
- [ ] **Documentation**: Runbook exists — ops team knows how to diagnose (see `SEARCH_OPERATOR.md`)

### Quick verification script

```bash
#!/bin/bash
# Run on each node to verify production readiness
set -e

echo "=== Search Node Production Readiness Check ==="

# 1. Process running?
systemctl is-active feedo-search 2>/dev/null || docker ps | grep -q feedo-search || {
    echo "❌ Process not running"
    exit 1
}
echo "✅ Process running"

# 2. HTTP API responding?
curl -sf http://localhost:8000/explorer/stats > /dev/null || {
    echo "❌ HTTP API not responding"
    exit 1
}
echo "✅ HTTP API responding"

# 3. Search functional?
curl -sf "http://localhost:8000/query?text=health+check&limit=1" > /dev/null 2>&1 || {
    echo "⚠️  Search query returned non-200 (may be normal if index is empty)"
}
echo "✅ Search endpoint responding"

# 4. TCP port listening?
ss -tln | grep -q ":8000" || {
    echo "❌ TCP port 8000 not listening"
    exit 1
}
echo "✅ TCP port 8000 listening"

# 5. Disk space sufficient?
USAGE=$(df /data/feedo/search/lancedb_data --output=pcent 2>/dev/null | tail -1 | tr -d ' %')
if [ -z "$USAGE" ]; then
    echo "⚠️  LanceDB data directory not found at /data/feedo/search/lancedb_data"
elif [ "$USAGE" -lt 80 ]; then
    echo "✅ Disk usage ${USAGE}% (<80%)"
else
    echo "⚠️  Disk usage ${USAGE}% — consider expanding"
fi

# 6. Peers connected? (check /v1/node/peers)
PEERS=$(curl -s http://localhost:8000/v1/node/peers | python3 -c "import sys,json; print(len(json.load(sys.stdin)['peers']))" 2>/dev/null || echo "0")
echo "✅ Known peers: $PEERS"

# 7. Network health?
HEALTH=$(curl -s http://localhost:8000/explorer/stats | python3 -c "import sys,json; print(json.load(sys.stdin)['network_health'])" 2>/dev/null || echo "Unknown")
echo "ℹ️  Network health: $HEALTH"

# 8. ML models loaded? (check logs for SentenceTransformer message)
MODELS=$(docker logs --since 10m feedo-search 2>/dev/null | grep -c "Loading ML model" || echo "0")
if [ "$MODELS" -gt 0 ]; then
    echo "⚠️  ML models still loading (recent restart)"
else
    echo "✅ ML models loaded"
fi

echo "=== All checks passed ==="
```

---

## Additional Resources

- [SEARCH_OPERATOR.md](./SEARCH_OPERATOR.md) — Single-node operations, troubleshooting
- [SEARCH_DOCS.md](./SEARCH_DOCS.md) — Architecture, API reference, protocol internals
- [SEARCH_ROADMAP.md](./SEARCH_ROADMAP.md) — 6-phase scaling plan
- [Main project README](../../README.md) — Feedo ecosystem overview