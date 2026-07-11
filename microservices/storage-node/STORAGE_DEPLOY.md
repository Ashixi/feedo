# Storage Node — Deployment Guide

> **Audience**: DevOps engineers deploying storage-node in production.
> **Prerequisites**: Familiarity with Docker, infrastructure-as-code, and Linux administration.
> For single-node operations, see [STORAGE_OPERATOR.md](./STORAGE_OPERATOR.md). For architecture, see [STORAGE_DOCS.md](./STORAGE_DOCS.md).

---

## 1. Deployment Overview

### Deployment matrix

| Scale | Nodes | Method | Orchestration |
|-------|-------|--------|---------------|
| **Single node** | 1 | Docker Compose | Manual (see Operator Guide) |
| **Small cluster** | 2–5 | Docker Compose + shared config | Manual or Ansible |
| **Medium cluster** | 5–50 | Docker Compose per node | Ansible + Terraform |
| **Large cluster** | 50+ | Kubernetes | K8s StatefulSet + Helm |

### Multi-node architecture (3 nodes example)

```
┌──────────────────────────────────────────────────────┐
│                    External Clients                   │
│              HTTP (upload/download/quota)             │
└───────┬──────────────────┬──────────────────┬────────┘
        │                  │                  │
   ┌────▼─────┐       ┌────▼─────┐       ┌────▼─────┐
   │ Node 0   │◄─────►│ Node 1   │◄─────►│ Node 2   │
   │ Genesis  │  P2P  │ Follower │  P2P  │ Follower │
   │ :8040    │  UDP  │ :8040    │  UDP  │ :8040    │
   └──────────┘       └──────────┘       └──────────┘
        │                  │                  │
   ┌────▼─────┐       ┌────▼─────┐       ┌────▼─────┐
   │ SSD:     │       │ SSD:     │       │ SSD:     │
   │ 1.7 TB   │       │ 500 GB   │       │ 500 GB   │
   └──────────┘       └──────────┘       └──────────┘
```

Each node independently stores shards. Data is erasure-coded (30+15) — any 30 of 45 shards reconstruct the file. Shards are distributed across all nodes via Kademlia DHT.

---

## 2. Infrastructure Requirements

### Per-node sizing

| Resource | Minimum | Recommended (production) |
|----------|---------|--------------------------|
| vCPUs | 2 | 4+ |
| RAM | 4 GB | 8 GB |
| Boot disk | 20 GB SSD | 40 GB SSD |
| Data disk | `SUM(quotas) × 1.5` | Dedicated SSD volume, XFS/ext4 |
| Network | 100 Mbps, static public IP | 1 Gbps |
| OS | Ubuntu 22.04/24.04 LTS | Ubuntu 24.04 LTS |

**Disk formula**: `(QUOTA_SITES_GB + QUOTA_BLOBS_GB) × 1.5 + (QUOTA_SOCIAL_MB + QUOTA_PROFILES_MB) / 1024 × 1.5` GB. The 50% overhead covers Reed-Solomon parity shards and Sled database metadata.

**Example**: Default quotas (100 GB + 1 TB + 500 MB + 100 MB) ≈ 1.1 TB → provision at least 1.7 TB.

### Cloud provider recommendations

| Provider | Best for | Notes |
|----------|----------|-------|
| **Hetzner** | Price/performance | Cheap dedicated vCPUs, good network. CX42 (4 vCPU/16 GB) works well. |
| **Netcup** | Budget storage nodes | Very cheap SSD-backed VPS. RS series. |
| **OVH** | Mid-range | Good DDoS protection. Advance series. |
| **DigitalOcean** | Quick setup | Simple UI. Droplets with attached volumes. |
| **AWS EC2** | Enterprise | `m7g.large` + EBS gp3. Higher cost. |

**Bare metal vs VPS**: Bare metal gives predictable IOPS for Sled. VPS with dedicated vCPUs is fine for most deployments. Avoid shared-CPU VPS (Sled write-heavy workload competes with neighbours).

---

## 3. Environment Variables — Production Profile

Complete `.env` for production storage nodes:

```bash
# ==========================================
# Identity (GENERATE ONCE — NEVER CHANGE)
# ==========================================
# Generate: openssl rand -hex 32
NODE_PRIVATE_KEY=

# ==========================================
# Network
# ==========================================
P2P_PORT=8040                     # MUST be UDP-open to internet
HTTP_PORT=3001                     # Optional: open for external API access
GRPC_PORT=50052                    # Internal only — do NOT expose

# Genesis node: leave empty
# Follower nodes: comma-separated multiaddrs of ≥2 existing nodes
BOOTSTRAP_NODES=

# ==========================================
# Storage
# ==========================================
DB_DIR=/data/feedo/storage         # Dedicated SSD mount point
DHT_RAM_CACHE_LIMIT=2000           # Increase for better DHT perf; lower if RAM-constrained

# ==========================================
# Quotas (adjust to your available disk)
# ==========================================
QUOTA_SITES_GB=500                 # Websites — highest priority
QUOTA_BLOBS_GB=2000                # Cloud storage — paid tier (future)
QUOTA_SOCIAL_MB=1000               # Nostr posts — temporary
QUOTA_PROFILES_MB=200              # User profiles — medium priority

# ==========================================
# Logging
# ==========================================
RUST_LOG=info                      # 'debug' for troubleshooting ONLY — generates excessive P2P logs
```

### Variable lifecycle

| Variable | Set once? | Can change later? |
|----------|-----------|-------------------|
| `NODE_PRIVATE_KEY` | Yes | **NO** — changing it changes your PeerId. All existing shards referencing the old PeerId become orphaned. |
| `P2P_PORT` | Yes | Change requires updating all bootstrap lists that reference your node |
| `BOOTSTRAP_NODES` | At deploy | Can add/remove anytime, restart required |
| `DB_DIR` | Yes | Can change but old data stays at old path |
| Quota vars | At deploy | Yes — increase and restart. Existing data preserved. |
| `RUST_LOG` | — | Yes — change and restart anytime |

---

## 4. Docker Compose Deployment

### Production `docker-compose.storage.yml`

```yaml
version: '3.8'

services:
  storage-node:
    image: itsshas/feedo-storage:latest   # Replace with actual image
    container_name: feedo-storage
    restart: unless-stopped
    network_mode: host                     # Required for direct UDP P2P
    env_file:
      - .env
    volumes:
      - /data/feedo/storage:/data/feedo/storage:rw
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
      test: ["CMD", "curl", "-f", "http://localhost:3001/api/v1/quota"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

**Key decisions**:

- `network_mode: host` — required because libp2p QUIC needs direct UDP access. Bridge mode with port mapping adds NAT complexity.
- `restart: unless-stopped` — survives Docker daemon restarts but allows manual `docker-compose stop`.
- Volume mount on host path — uses dedicated SSD mount point, not a Docker named volume (easier backup).
- Resource limits — prevents runaway memory/CPU from affecting other services on the host.

### Deploy

```bash
# On each node
scp docker-compose.storage.yml .env user@node:/opt/feedo/
ssh user@node
cd /opt/feedo
docker-compose -f docker-compose.storage.yml up -d
docker-compose -f docker-compose.storage.yml logs -f
```

### Multi-node with Docker Compose

Deploy to 3 nodes (node0, node1, node2) with identical `docker-compose.storage.yml` but different `.env`:

| Node | `BOOTSTRAP_NODES` | `NODE_PRIVATE_KEY` |
|------|-------------------|---------------------|
| node0 (genesis) | (empty) | key0 |
| node1 (follower) | `/ip4/{node0_ip}/udp/8040/quic-v1/p2p/{peer0}` | key1 |
| node2 (follower) | `/ip4/{node0_ip}/udp/8040/quic-v1/p2p/{peer0},/ip4/{node1_ip}/udp/8040/quic-v1/p2p/{peer1}` | key2 |

---

## 5. Kubernetes Deployment

### Key considerations for K8s

- **`hostNetwork: true`** recommended — avoids UDP NAT issues with ClusterIP/NodePort
- **StatefulSet** — each pod needs stable identity (PeerId tied to private key)
- **PersistentVolumeClaim** — SSD StorageClass, `ReadWriteOnce`
- **podAntiAffinity** — spread pods across nodes for resilience
- **`terminationGracePeriodSeconds: 60`** — allows graceful Kademlia disconnection

### `k8s/storage-statefulset.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: feedo-storage
---
apiVersion: v1
kind: Secret
metadata:
  name: storage-secrets
  namespace: feedo-storage
type: Opaque
stringData:
  node-private-key-0: "hex-key-for-node-0"
  node-private-key-1: "hex-key-for-node-1"
  node-private-key-2: "hex-key-for-node-2"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: storage-config
  namespace: feedo-storage
data:
  P2P_PORT: "8040"
  HTTP_PORT: "3001"
  GRPC_PORT: "50052"
  DB_DIR: "/data/feedo/storage"
  DHT_RAM_CACHE_LIMIT: "2000"
  QUOTA_SITES_GB: "500"
  QUOTA_BLOBS_GB: "2000"
  QUOTA_SOCIAL_MB: "1000"
  QUOTA_PROFILES_MB: "200"
  RUST_LOG: "info"
---
apiVersion: v1
kind: Service
metadata:
  name: storage-headless
  namespace: feedo-storage
spec:
  clusterIP: None                   # Headless — each pod reachable by DNS
  selector:
    app: storage-node
  ports:
    - name: p2p
      port: 8040
      protocol: UDP
    - name: http
      port: 3001
      protocol: TCP
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: storage-node
  namespace: feedo-storage
spec:
  serviceName: storage-headless
  replicas: 3
  podManagementPolicy: Parallel     # Start all simultaneously
  selector:
    matchLabels:
      app: storage-node
  template:
    metadata:
      labels:
        app: storage-node
    spec:
      hostNetwork: true             # Direct UDP — no NAT
      terminationGracePeriodSeconds: 60
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: storage-node
              topologyKey: kubernetes.io/hostname
      containers:
        - name: storage-node
          image: itsshas/feedo-storage:latest
          envFrom:
            - configMapRef:
                name: storage-config
          env:
            - name: NODE_PRIVATE_KEY
              valueFrom:
                secretKeyRef:
                  name: storage-secrets
                  key: node-private-key-$(ORDINAL)   # Requires K8s 1.28+ or envsubst init container
            - name: BOOTSTRAP_NODES
              value: ""                              # Genesis: empty. Followers: set manually.
          ports:
            - containerPort: 8040
              protocol: UDP
            - containerPort: 3001
              protocol: TCP
          resources:
            requests:
              memory: "2Gi"
              cpu: "2"
            limits:
              memory: "8Gi"
              cpu: "4"
          volumeMounts:
            - name: storage-data
              mountPath: /data/feedo/storage
          readinessProbe:
            httpGet:
              path: /api/v1/quota
              port: 3001
            initialDelaySeconds: 30
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /api/v1/quota
              port: 3001
            initialDelaySeconds: 60
            periodSeconds: 30
  volumeClaimTemplates:
    - metadata:
        name: storage-data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: "ssd"
        resources:
          requests:
            storage: 2Ti              # Sized to your quotas × 1.5
```

### Deploy to K8s

```bash
kubectl apply -f k8s/storage-statefulset.yaml
kubectl -n feedo-storage get pods -w
kubectl -n feedo-storage logs -f storage-node-0
```

### Bootstrapping on K8s

Node 0 starts first (genesis). After its PeerId appears in logs, compute its multiaddr:
```
/ip4/{NODE_EXTERNAL_IP}/udp/8040/quic-v1/p2p/{PEER_ID}
```
Then patch nodes 1 and 2:
```bash
kubectl -n feedo-storage set env statefulset/storage-node \
  BOOTSTRAP_NODES="/ip4/1.2.3.4/udp/8040/quic-v1/p2p/12D3KooW..."
kubectl -n feedo-storage rollout restart statefulset/storage-node
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
│   ├── deploy.yml           # Main playbook: install deps, deploy compose, start
│   ├── update.yml           # Rolling update: git pull, build, restart
│   ├── inventory/
│   │   └── hosts.yml        # Generated from terraform output
│   └── group_vars/
│       └── all.yml          # NODE_PRIVATE_KEY (vault encrypted), quotas
└── docker-compose.storage.yml
```

### Terraform snippet (Hetzner example)

```hcl
resource "hcloud_server" "storage_node" {
  count       = var.node_count
  name        = "feedo-storage-${count.index}"
  server_type = "cx42"           # 4 vCPU, 16 GB RAM
  image       = "ubuntu-24.04"
  location    = "nbg1"           # Nuremberg

  public_net {
    ipv4_enabled = true
  }
}

resource "hcloud_volume" "storage_data" {
  count     = var.node_count
  name      = "feedo-storage-data-${count.index}"
  size      = 2000               # 2 TB
  server_id = hcloud_server.storage_node[count.index].id
  format    = "ext4"
  automount = true
}

resource "hcloud_firewall" "storage" {
  name = "feedo-storage"
  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "8040"
    source_ips = ["0.0.0.0/0"]
  }
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "3001"
    source_ips = ["0.0.0.0/0"]      # Optional — restrict to your IPs if possible
  }
}
```

### Ansible snippet (deploy playbook)

```yaml
- name: Deploy Feedo Storage Node
  hosts: storage_nodes
  become: yes
  vars:
    db_dir: /data/feedo/storage
  tasks:
    - name: Install Docker
      apt:
        name: docker.io
        state: present

    - name: Create data directory
      file:
        path: "{{ db_dir }}"
        state: directory
        owner: "1000"
        group: "1000"

    - name: Copy compose file
      copy:
        src: docker-compose.storage.yml
        dest: /opt/feedo/docker-compose.storage.yml

    - name: Template .env
      template:
        src: .env.j2
        dest: /opt/feedo/.env
        mode: 0600

    - name: Start storage node
      docker_compose:
        project_src: /opt/feedo
        files: docker-compose.storage.yml
        state: present
```

### `ansible/group_vars/all.yml` (vault-encrypted)

```yaml
# ansible-vault encrypt group_vars/all.yml
vault_node_private_keys:
  - "hex-key-node-0"
  - "hex-key-node-1"
  - "hex-key-node-2"
```

---

## 7. Multi-Node Cluster Setup

### Step-by-step: 3-node cluster

**Step 1 — Deploy genesis node (Node 0)**

```bash
# .env for Node 0
BOOTSTRAP_NODES=               # Empty — this IS the network
NODE_PRIVATE_KEY=<key0>
```

Start Node 0. Wait for logs:
```
Local peer id: PeerId("12D3KooW...")
Listening on P2P address: /ip4/0.0.0.0/udp/8040/quic-v1
```

**Step 2 — Build genesis multiaddr**

```
/ip4/{NODE0_PUBLIC_IP}/udp/8040/quic-v1/p2p/12D3KooW...
```

**Step 3 — Deploy follower nodes (Node 1, Node 2)**

```bash
# .env for Node 1
BOOTSTRAP_NODES=/ip4/{NODE0_IP}/udp/8040/quic-v1/p2p/{NODE0_PEER_ID}
NODE_PRIVATE_KEY=<key1>

# .env for Node 2 (redundant bootstrap)
BOOTSTRAP_NODES=/ip4/{NODE0_IP}/udp/8040/quic-v1/p2p/{NODE0_PEER_ID},/ip4/{NODE1_IP}/udp/8040/quic-v1/p2p/{NODE1_PEER_ID}
NODE_PRIVATE_KEY=<key2>
```

**Step 4 — Verify cluster**

```bash
# On each node, check logs for connections
docker-compose logs | grep "Connection established"

# Node 0 should see connections from Node 1 and Node 2
# Node 1 should see connections from Node 0 and Node 2
# Node 2 should see connections from Node 0 and Node 1
```

**Step 5 — End-to-end test**

```bash
# Upload file to Node 0
curl -X POST http://{NODE0_IP}:3001/upload \
  -H "X-Feedo-Storage-Class: blob" \
  -F "file=@test.txt"
# → returns hash (e.g., abc123...)

# Download from Node 2 (different node)
curl http://{NODE2_IP}:3001/download/abc123...
# → should return the same file

# Check quota on all three nodes
curl http://{NODE0_IP}:3001/api/v1/quota
curl http://{NODE1_IP}:3001/api/v1/quota
curl http://{NODE2_IP}:3001/api/v1/quota
```

### Adding a node to an existing cluster

1. Generate new `NODE_PRIVATE_KEY` (`openssl rand -hex 32`)
2. Set `BOOTSTRAP_NODES` to 2+ existing node multiaddrs
3. Deploy and start. Node discovers the DHT and joins within ~30 seconds.

### Removing a node

```bash
docker-compose -f docker-compose.storage.yml stop
# Or: kubectl scale statefulset storage-node --replicas=2
```

The Kademlia DHT automatically detects the node is gone. Shards that were on that node become unavailable — the network's self-healing (reactive in Phase 1, proactive in Phase 3) will re-encode and redistribute them. **No manual rebalancing needed.**

---

## 8. Networking Deep Dive

### Why UDP/QUIC

Storage-node uses libp2p with **QUIC transport over UDP**. This is deliberate:
- **Multiplexed streams** — multiple concurrent shard transfers on one port
- **No head-of-line blocking** — unlike TCP, a lost packet in one stream doesn't block others
- **Better NAT traversal** — QUIC connection IDs survive IP changes
- **Mandatory encryption** — noise + QUIC TLS 1.3

### Bandwidth estimation

Each file upload generates network traffic:
- **Outgoing** (uploading node): `(DATA_SHARDS + PARITY_SHARDS) × shard_size` bytes sent to peers — currently `45 × (file_size / 30)` ≈ `1.5 × file_size`
- **Incoming** (storing peers): `shard_size` bytes received per assigned shard — `file_size / 30` per shard

**Example**: Uploading a 300 MB file → Node sends ~450 MB split across 45 shards to peers. Each of the 45 target peers receives ~10 MB (one shard). Plan upload bandwidth accordingly — a 1 Gbps link handles ~80 MB/s, so this upload takes ~6 seconds of network time.

### Cloud provider firewall setup

| Provider | How to open UDP 8040 |
|----------|---------------------|
| **Hetzner** | Cloud Console → Firewalls → Create firewall → Inbound rule: UDP, Port 8040, Source 0.0.0.0/0. Apply to server. |
| **AWS** | EC2 → Security Groups → Inbound rules → Custom UDP, Port 8040, Source 0.0.0.0/0 |
| **GCP** | VPC Network → Firewall → Create rule → Allow ingress, UDP:8040, Target: instance tag `feedo-storage` |
| **DigitalOcean** | Networking → Firewalls → Create firewall → Inbound: UDP, Port 8040, All sources. Apply to Droplet. |

**Double check**: Cloud provider firewall + OS-level firewall (ufw/iptables). Both must allow UDP 8040.

---

## 9. Secrets Management

### The only critical secret: `NODE_PRIVATE_KEY`

This 64-character hex string is your node's Ed25519 private key. It determines your `PeerId` — your identity on the Kademlia DHT.

**Generation**:
```bash
openssl rand -hex 32
# → 64-character hex string
```

**Storage options** (ranked by security):

| Method | Security | Complexity | Best for |
|--------|----------|------------|----------|
| Docker secrets | High | Medium | Docker Swarm |
| Kubernetes Secrets | High | Medium | K8s clusters |
| Ansible Vault | High | Medium | Ansible-managed infra |
| HashiCorp Vault | Highest | High | Enterprise |
| `.env` with `chmod 600` | Medium | Low | Single node / small clusters |

**Key rotation**: NOT supported. If you change `NODE_PRIVATE_KEY`, your node gets a new PeerId. All shards stored on other peers that reference your old PeerId become orphaned. The network will eventually self-heal (re-encode those files), but during the transition period, downloads may fail.

**If key is compromised**: An attacker with your private key can impersonate your node on the DHT. Generate a new key, redeploy. Accept that some shard references become temporarily invalid. For production, store the key in a vault/secret manager from day one.

---

## 10. Monitoring Stack

### Current built-in endpoints

```bash
# Quota usage per class (parse as JSON)
curl http://localhost:3001/api/v1/quota

# Recent uploads
curl http://localhost:3001/api/files/recent
```

### Recommended: Prometheus + Grafana

**Prometheus scrape config** (`prometheus.yml`):

```yaml
scrape_configs:
  - job_name: 'feedo-storage'
    scrape_interval: 30s
    static_configs:
      - targets:
          - 'node0:3001'
          - 'node1:3001'
          - 'node2:3001'
    metrics_path: '/api/v1/quota'
    # Note: /api/v1/quota returns JSON, not Prometheus format.
    # Use json_exporter (github.com/prometheus-community/json_exporter) or a custom sidecar.
```

**Recommended: `json_exporter` configuration** to convert `/api/v1/quota` JSON → Prometheus metrics:

```yaml
# json_exporter config
modules:
  storage_quota:
    headers:
      Accept: application/json
    metrics:
      - name: feedo_storage_used_bytes
        type: object
        path: '{.site,.blob,.social_post,.profile}'
        labels:
          class: '{.site,.blob,.social_post,.profile}'
        values:
          used_bytes: used_bytes
          max_bytes: max_bytes
```

**Node Exporter** (system metrics): CPU, RAM, disk I/O, network throughput. Install on every node:
```bash
sudo apt install prometheus-node-exporter
```

**Grafana dashboard panels**:

| Panel | Metric | Type |
|-------|--------|------|
| Quota usage per class | `feedo_storage_used_bytes{used}` / `feedo_storage_used_bytes{max}` | Gauge (4 panels) |
| Peer count | Log-based: count `Connection established` events | Stat |
| Upload rate | Rate of upload requests (application-level) | Graph |
| Disk usage | `node_filesystem_avail_bytes{mountpoint="/data"}` | Gauge |
| Network throughput | `node_network_receive_bytes_total{device="eth0"}` | Graph |
| RAM usage | `node_memory_MemAvailable_bytes` | Gauge |

### Alerting rules (Prometheus AlertManager)

```yaml
groups:
  - name: feedo-storage
    rules:
      - alert: StorageQuotaHigh
        expr: (feedo_storage_used_bytes{used="used_bytes"} / feedo_storage_used_bytes{max="max_bytes"}) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Storage quota >80% for class {{ $labels.class }}"

      - alert: StorageQuotaFull
        expr: (feedo_storage_used_bytes{used="used_bytes"} / feedo_storage_used_bytes{max="max_bytes"}) > 0.95
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Storage quota >95% for class {{ $labels.class }} — uploads will be rejected"

      - alert: StorageNodeDown
        expr: up{job="feedo-storage"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Storage node {{ $labels.instance }} is down"

      - alert: DiskFull
        expr: node_filesystem_avail_bytes{mountpoint="/data"} / node_filesystem_size_bytes{mountpoint="/data"} < 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Data disk >90% full on {{ $labels.instance }}"
```

### Log aggregation with Loki + Promtail

Collect storage-node logs and create alerts for:
- `[Quota] WARNING:` → quota exceeded (see above — prefer metric-based alert)
- `Error dialing` → bootstrap node unreachable
- `Connection established` → count over time for peer health

---

## 11. CI/CD Pipeline

### GitHub Actions — build, test, deploy

```yaml
name: Storage Node CI/CD

on:
  push:
    branches: [main]
    paths:
      - 'microservices/storage-node/**'
      - 'microservices/shared-proto/**'
  pull_request:
    paths:
      - 'microservices/storage-node/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - name: Check compilation
        run: cargo check --manifest-path microservices/storage-node/Cargo.toml
      - name: Run unit tests
        run: cargo test --manifest-path microservices/storage-node/Cargo.toml --bin storage-node

  deploy-canary:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to canary node
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.CANARY_HOST }}
          username: feedo
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /opt/feedo
            git pull origin main
            cargo build --release --manifest-path microservices/storage-node/Cargo.toml
            sudo systemctl restart feedo-storage
            sleep 30
            curl -f http://localhost:3001/api/v1/quota || exit 1

  deploy-production:
    needs: deploy-canary
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    strategy:
      matrix:
        host: ${{ fromJSON(secrets.PRODUCTION_HOSTS) }}
    steps:
      - name: Deploy to production
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ matrix.host }}
          username: feedo
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /opt/feedo
            git pull origin main
            cargo build --release --manifest-path microservices/storage-node/Cargo.toml
            sudo systemctl restart feedo-storage
```

### Canary deployment strategy

1. Deploy to 1 node (canary)
2. Run health check (`curl /api/v1/quota`)
3. Verify peer connections restored
4. Wait 5 minutes — observe monitoring
5. Deploy to remaining nodes (rolling, one at a time)

### Rollback

```bash
# On each node
cd /opt/feedo
git checkout <previous-commit-sha>
cargo build --release --manifest-path microservices/storage-node/Cargo.toml
sudo systemctl restart feedo-storage
```

Docker-based rollback:
```bash
docker-compose -f docker-compose.storage.yml pull storage-node:<previous-tag>
docker-compose -f docker-compose.storage.yml up -d
```

---

## 12. Production Hardening Checklist

Before going to production, verify every item:

- [ ] **Network**: UDP port 8040 open in cloud provider firewall AND OS firewall (ufw/iptables)
- [ ] **Network**: TCP port 3001 open only if external API access is needed (restrict source IPs if possible)
- [ ] **Network**: TCP port 50052 NOT exposed (gRPC — internal only)
- [ ] **Identity**: `NODE_PRIVATE_KEY` generated, stored in secrets manager, backed up offline
- [ ] **Storage**: `DB_DIR` on dedicated SSD volume, not root partition, XFS or ext4
- [ ] **Storage**: Disk space ≥ `SUM(quotas) × 1.5`, with monitoring alert at 80%
- [ ] **Resources**: CPU/memory limits configured (Docker: `deploy.resources.limits`, systemd: `MemoryMax`/`CPUQuota`)
- [ ] **Resources**: `DHT_RAM_CACHE_LIMIT` tuned — 2000 for RAM ≥8 GB, 500 for 2-4 GB
- [ ] **Logs**: Log rotation configured (Docker: `max-size`/`max-file`, systemd: journald `MaxRetentionSec`)
- [ ] **Logs**: `RUST_LOG=info` (not debug — debug generates gigabytes of P2P gossip logs per day)
- [ ] **Process**: Runs as non-root user (`User=feedo` in systemd, `user: "1000:1000"` in Docker)
- [ ] **Process**: Automatic restart on failure (`restart: unless-stopped` in Docker, `Restart=always` in systemd)
- [ ] **Process**: `LimitNOFILE=65536` (storage-node opens many concurrent P2P connections)
- [ ] **Bootstrap**: ≥2 redundant bootstrap nodes in `BOOTSTRAP_NODES` for follower nodes
- [ ] **Monitoring**: Quota API scraped by Prometheus, alerts configured for >80% quota + node down
- [ ] **Monitoring**: System metrics (CPU, RAM, disk, network) collected via Node Exporter
- [ ] **Backup**: `peer_key.bin` backed up to separate location (off-server)
- [ ] **CI/CD**: Automated tests pass before deploy, canary deployment before full rollout
- [ ] **Documentation**: Runbook exists — ops team knows how to diagnose (see Section 10 of Operator Guide)

### Quick verification script

```bash
#!/bin/bash
# Run on each node to verify production readiness
set -e

echo "=== Storage Node Production Readiness Check ==="

# 1. Process running?
systemctl is-active feedo-storage || docker ps | grep storage-node || exit 1
echo "✅ Process running"

# 2. Quota API responding?
curl -sf http://localhost:3001/api/v1/quota > /dev/null
echo "✅ Quota API responding"

# 3. UDP port listening?
ss -uln | grep -q 8040
echo "✅ P2P port listening (UDP 8040)"

# 4. Disk space sufficient?
USAGE=$(df /data/feedo/storage --output=pcent | tail -1 | tr -d ' %')
if [ "$USAGE" -lt 80 ]; then
    echo "✅ Disk usage ${USAGE}% (<80%)"
else
    echo "⚠️  Disk usage ${USAGE}% — consider expanding"
fi

# 5. Peers connected? (check logs last 5 min)
PEERS=$(journalctl -u feedo-storage --since "5 min ago" 2>/dev/null | grep -c "Connection established" || \
        docker logs --since 5m feedo-storage 2>&1 | grep -c "Connection established" || echo "0")
echo "✅ Peers connected in last 5 min: $PEERS"

echo "=== All checks passed ==="
```

---

## Additional Resources

- [STORAGE_OPERATOR.md](./STORAGE_OPERATOR.md) — Single-node operations, troubleshooting, quota planning
- [STORAGE_DOCS.md](./STORAGE_DOCS.md) — Architecture, API reference, protocol internals
- [STORAGE_ROADMAP.md](./STORAGE_ROADMAP.md) — 5-phase scaling plan
- [Main project README](../../README.md) — Feedo ecosystem overview