# Consensus Node — Deployment Guide

> **Audience**: DevOps engineers deploying consensus-node in production.
> **Prerequisites**: Familiarity with Docker, infrastructure-as-code, and Linux administration.
> For single-node operations, see [CONSENSUS_OPERATOR.md](./CONSENSUS_OPERATOR.md). For architecture, see [CONSENSUS_DOCS.md](./CONSENSUS_DOCS.md).

---

## 1. Deployment Overview

### Deployment matrix

| Scale | Nodes | Method | Orchestration |
|-------|-------|--------|---------------|
| **Single node** | 1 | Docker Compose | Manual (see Operator Guide) |
| **Small cluster** | 2–5 | Docker Compose + shared config | Manual or Ansible |
| **Medium cluster** | 5–50 | Docker Compose per node | Ansible + Terraform |
| **Large cluster** | 50+ | Kubernetes | K8s StatefulSet + Helm |

### Multi-node architecture (3 validators example)

```
┌──────────────────────────────────────────────────────┐
│                    External Clients                   │
│                   HTTP (name/DID API)                 │
└───────┬──────────────────┬──────────────────┬────────┘
        │                  │                  │
   ┌────▼─────┐       ┌────▼─────┐       ┌────▼─────┐
   │ Node 0   │◄─────►│ Node 1   │◄─────►│ Node 2   │
   │ Genesis  │  P2P  │ Follower │  P2P  │ Follower │
   │ :8041    │  UDP  │ :8041    │  UDP  │ :8041    │
   └──────────┘       └──────────┘       └──────────┘
        │                  │                  │
        │  PBFT Direct     │  PBFT Direct     │  PBFT Direct
        │  (Phase 1)       │  (Phase 1)       │  (Phase 1)
        ▼                  ▼                  ▼
   ┌─────────────────────────────────────────────────┐
   │         Gossipsub mesh (peer discovery)          │
   │    + Kademlia DHT (name records, snapshots)      │
   └─────────────────────────────────────────────────┘
```

Each validator participates in PBFT consensus. PBFT votes go **direct** between committee members (Phase 1 request-response), while gossipsub handles peer discovery and backward compatibility. Names and DID records are distributed via Kademlia DHT.

---

## 2. Infrastructure Requirements

### Per-node sizing

| Resource | Minimum | Recommended (production) |
|----------|---------|--------------------------|
| vCPUs | 2 | 4+ |
| RAM | 2 GB | 4 GB |
| Boot disk | 20 GB SSD | 40 GB SSD |
| Data disk | Not required | Not required |
| Network | 10 Mbps, static public IP | 100 Mbps |
| OS | Ubuntu 22.04/24.04 LTS | Ubuntu 24.04 LTS |

Consensus-node is **lightweight** — it stores only current state (names, balances, DIDs), not transaction history. After Phase 1.5, storage is bounded at ~10-20 MB per node regardless of network age. No large data disk needed.

**Bandwidth estimate**: For a 21-validator committee, each transaction generates ~3 phases × 21 peers = 63 messages × ~500 bytes = ~31 KB. At 10 transactions/minute, that's ~5 KB/s. Even at 100 tx/min, ~50 KB/s. Network requirements are minimal compared to storage-node.

### Cloud provider recommendations

| Provider | Best for | Notes |
|----------|----------|-------|
| **Hetzner** | Price/performance | CX22 (2 vCPU/4 GB) is plenty. ~€4/month. |
| **Netcup** | Budget | RS 1000 or higher. Very cheap VPS. |
| **OVH** | Mid-range | Good DDoS protection. VPS Starter. |
| **DigitalOcean** | Quick setup | Simple UI. Basic Droplet ($6/month) works. |
| **AWS EC2** | Enterprise | `t3.small` or `t4g.small`. Higher cost. |

**Bare metal vs VPS**: Not relevant for consensus-node — the workload is CPU-light (PBFT voting, DHT lookups). A cheap VPS with dedicated vCPUs is sufficient.

---

## 3. Environment Variables — Production Profile

Complete `.env` for production consensus nodes:

```bash
# ==========================================
# Identity (GENERATE ONCE — NEVER CHANGE)
# ==========================================
# Generate: openssl rand -hex 32
NODE_PRIVATE_KEY=
# Set to your ETH address BEFORE first start:
NODE_WALLET_ADDRESS=0x0000000000000000000000000000000000000000

# ==========================================
# Network
# ==========================================
P2P_PORT=8041                     # MUST be UDP-open to internet
HTTP_PORT=3000                     # Optional: open for external name API access
GRPC_PORT=50051                    # Internal only — do NOT expose

# Genesis node: leave empty
# Follower nodes: comma-separated multiaddrs of ≥2 existing nodes
BOOTSTRAP_NODES=

# ==========================================
# Consensus
# ==========================================
EPOCH_DURATION_SECS=600            # 10 minutes per epoch
CONSENSUS_DIRECT_MODE=true         # Phase 1: direct PBFT messages (recommended)

# ==========================================
# Blockchain
# ==========================================
# Polygon RPC for on-chain committee. Use your own Infura/Alchemy key for reliability.
ETH_RPC_URL=https://polygon-rpc.com

# ==========================================
# Storage
# ==========================================
DB_DIR=/data/feedo/consensus       # SSD mount point

# ==========================================
# Logging
# ==========================================
RUST_LOG=info                      # 'debug' for troubleshooting ONLY — generates excessive P2P logs
```

### Variable lifecycle

| Variable | Set once? | Can change later? |
|----------|-----------|-------------------|
| `NODE_PRIVATE_KEY` | Yes | **NO** — changing it changes your PeerId. All committee history is tied to the old PeerId. |
| `NODE_WALLET_ADDRESS` | Yes | **NO** — changing it changes your identity in the committee. Reputation resets to 10. |
| `P2P_PORT` | Yes | Change requires updating all bootstrap lists that reference your node |
| `BOOTSTRAP_NODES` | At deploy | Can add/remove anytime, restart required |
| `DB_DIR` | Yes | Can change but old data stays at old path |
| `EPOCH_DURATION_SECS` | At deploy | Yes — change and restart. Affects committee rotation frequency. |
| `CONSENSUS_DIRECT_MODE` | — | Yes — change and restart anytime |
| `ETH_RPC_URL` | At deploy | Yes — change and restart anytime |
| `RUST_LOG` | — | Yes — change and restart anytime |

---

## 4. Docker Compose Deployment

### Production `docker-compose.consensus.yml`

```yaml
version: '3.8'

services:
  consensus-node:
    image: itsshas/feedo-consensus:latest   # Replace with actual image
    container_name: feedo-consensus
    restart: unless-stopped
    network_mode: host                     # Required for direct UDP P2P
    env_file:
      - .env
    volumes:
      - /data/feedo/consensus:/data/feedo/consensus:rw
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: '4'
        reservations:
          memory: 1G
          cpus: '1'
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/resolve/test.feedo"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

**Key decisions**:

- `network_mode: host` — required because libp2p QUIC needs direct UDP access for PBFT voting and peer discovery.
- `restart: unless-stopped` — survives Docker daemon restarts but allows manual `docker-compose stop`.
- Volume mount on host path — uses dedicated SSD mount point, not a Docker named volume (easier backup).
- Resource limits — consensus-node is light; 4 GB memory limit is generous.
- Healthcheck uses `/resolve/test.feedo` — verifies HTTP API is responding (returns null for unknown names, which is a successful response).

### Deploy

```bash
# On each node
scp docker-compose.consensus.yml .env user@node:/opt/feedo/
ssh user@node
cd /opt/feedo
docker-compose -f docker-compose.consensus.yml up -d
docker-compose -f docker-compose.consensus.yml logs -f
```

### Multi-node with Docker Compose

Deploy to 3 nodes (node0, node1, node2) with identical `docker-compose.consensus.yml` but different `.env`:

| Node | `BOOTSTRAP_NODES` | `NODE_WALLET_ADDRESS` | `NODE_PRIVATE_KEY` |
|------|-------------------|------------------------|---------------------|
| node0 (genesis) | (empty) | wallet0 | key0 |
| node1 (follower) | `/ip4/{node0_ip}/udp/8041/quic-v1/p2p/{peer0}` | wallet1 | key1 |
| node2 (follower) | `/ip4/{node0_ip}/udp/8041/quic-v1/p2p/{peer0},/ip4/{node1_ip}/udp/8041/quic-v1/p2p/{peer1}` | wallet2 | key2 |

---

## 5. Kubernetes Deployment

### Key considerations for K8s

- **`hostNetwork: true`** recommended — avoids UDP NAT issues with ClusterIP/NodePort
- **StatefulSet** — each pod needs stable identity (PeerId tied to private key, wallet address for committee)
- **PersistentVolumeClaim** — SSD StorageClass, `ReadWriteOnce` (small — 20 GB is plenty)
- **podAntiAffinity** — spread pods across nodes for resilience
- **`terminationGracePeriodSeconds: 60`** — allows graceful Kademlia disconnection

### `k8s/consensus-statefulset.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: feedo-consensus
---
apiVersion: v1
kind: Secret
metadata:
  name: consensus-secrets
  namespace: feedo-consensus
type: Opaque
stringData:
  node-private-key-0: "hex-key-for-node-0"
  node-private-key-1: "hex-key-for-node-1"
  node-private-key-2: "hex-key-for-node-2"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: consensus-config
  namespace: feedo-consensus
data:
  P2P_PORT: "8041"
  HTTP_PORT: "3000"
  GRPC_PORT: "50051"
  DB_DIR: "/data/feedo/consensus"
  EPOCH_DURATION_SECS: "600"
  CONSENSUS_DIRECT_MODE: "true"
  ETH_RPC_URL: "https://polygon-rpc.com"
  RUST_LOG: "info"
---
apiVersion: v1
kind: Service
metadata:
  name: consensus-headless
  namespace: feedo-consensus
spec:
  clusterIP: None                   # Headless — each pod reachable by DNS
  selector:
    app: consensus-node
  ports:
    - name: p2p
      port: 8041
      protocol: UDP
    - name: http
      port: 3000
      protocol: TCP
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: consensus-node
  namespace: feedo-consensus
spec:
  serviceName: consensus-headless
  replicas: 3
  podManagementPolicy: Parallel     # Start all simultaneously
  selector:
    matchLabels:
      app: consensus-node
  template:
    metadata:
      labels:
        app: consensus-node
    spec:
      hostNetwork: true             # Direct UDP — no NAT
      terminationGracePeriodSeconds: 60
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: consensus-node
              topologyKey: kubernetes.io/hostname
      containers:
        - name: consensus-node
          image: itsshas/feedo-consensus:latest
          envFrom:
            - configMapRef:
                name: consensus-config
          env:
            - name: NODE_PRIVATE_KEY
              valueFrom:
                secretKeyRef:
                  name: consensus-secrets
                  key: node-private-key-$(ORDINAL)   # Requires K8s 1.28+ or envsubst init container
            - name: NODE_WALLET_ADDRESS
              value: ""                              # Set per-pod — different wallet per ordinal
            - name: BOOTSTRAP_NODES
              value: ""                              # Genesis: empty. Followers: set manually.
          ports:
            - containerPort: 8041
              protocol: UDP
            - containerPort: 3000
              protocol: TCP
          resources:
            requests:
              memory: "1Gi"
              cpu: "1"
            limits:
              memory: "4Gi"
              cpu: "4"
          volumeMounts:
            - name: consensus-data
              mountPath: /data/feedo/consensus
          readinessProbe:
            httpGet:
              path: /resolve/test.feedo
              port: 3000
            initialDelaySeconds: 30
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /resolve/test.feedo
              port: 3000
            initialDelaySeconds: 60
            periodSeconds: 30
  volumeClaimTemplates:
    - metadata:
        name: consensus-data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: "ssd"
        resources:
          requests:
            storage: 20Gi              # Small — consensus state is compact
```

### Deploy to K8s

```bash
kubectl apply -f k8s/consensus-statefulset.yaml
kubectl -n feedo-consensus get pods -w
kubectl -n feedo-consensus logs -f consensus-node-0
```

### Bootstrapping on K8s

Node 0 starts first (genesis). After its PeerId appears in logs, compute its multiaddr:
```
/ip4/{NODE_EXTERNAL_IP}/udp/8041/quic-v1/p2p/{PEER_ID}
```
Then patch nodes 1 and 2:
```bash
kubectl -n feedo-consensus set env statefulset/consensus-node \
  BOOTSTRAP_NODES="/ip4/1.2.3.4/udp/8041/quic-v1/p2p/12D3KooW..."
kubectl -n feedo-consensus rollout restart statefulset/consensus-node
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
│       └── all.yml          # NODE_PRIVATE_KEY (vault encrypted), wallet addresses
└── docker-compose.consensus.yml
```

### Terraform snippet (Hetzner example)

```hcl
resource "hcloud_server" "consensus_node" {
  count       = var.node_count
  name        = "feedo-consensus-${count.index}"
  server_type = "cx22"           # 2 vCPU, 4 GB RAM
  image       = "ubuntu-24.04"
  location    = "nbg1"           # Nuremberg

  public_net {
    ipv4_enabled = true
  }

  # Consensus node only needs boot disk — no volume needed
}

resource "hcloud_firewall" "consensus" {
  name = "feedo-consensus"
  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "8041"
    source_ips = ["0.0.0.0/0"]
  }
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "3000"
    source_ips = ["0.0.0.0/0"]      # Optional — restrict to your IPs if possible
  }
}
```

### Ansible snippet (deploy playbook)

```yaml
- name: Deploy Feedo Consensus Node
  hosts: consensus_nodes
  become: yes
  vars:
    db_dir: /data/feedo/consensus
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
        src: docker-compose.consensus.yml
        dest: /opt/feedo/docker-compose.consensus.yml

    - name: Template .env
      template:
        src: .env.j2
        dest: /opt/feedo/.env
        mode: 0600

    - name: Start consensus node
      docker_compose:
        project_src: /opt/feedo
        files: docker-compose.consensus.yml
        state: present
```

### `ansible/group_vars/all.yml` (vault-encrypted)

```yaml
# ansible-vault encrypt group_vars/all.yml
vault_node_private_keys:
  - "hex-key-node-0"
  - "hex-key-node-1"
  - "hex-key-node-2"

vault_wallet_addresses:
  - "0xwallet0..."
  - "0xwallet1..."
  - "0xwallet2..."
```

---

## 7. Multi-Node Cluster Setup

### Step-by-step: 3-node cluster

**Step 1 — Deploy genesis node (Node 0)**

```bash
# .env for Node 0
BOOTSTRAP_NODES=               # Empty — this IS the network
NODE_PRIVATE_KEY=<key0>
NODE_WALLET_ADDRESS=<wallet0>
```

Start Node 0. Wait for logs:
```
Consensus Local peer id: PeerId("12D3KooW...")
Node Wallet Address (committee identity): 0xwallet0...
Consensus node listening on P2P address: /ip4/0.0.0.0/udp/8041/quic-v1
```

**Step 2 — Build genesis multiaddr**

```
/ip4/{NODE0_PUBLIC_IP}/udp/8041/quic-v1/p2p/12D3KooW...
```

**Step 3 — Deploy follower nodes (Node 1, Node 2)**

```bash
# .env for Node 1
BOOTSTRAP_NODES=/ip4/{NODE0_IP}/udp/8041/quic-v1/p2p/{NODE0_PEER_ID}
NODE_PRIVATE_KEY=<key1>
NODE_WALLET_ADDRESS=<wallet1>

# .env for Node 2 (redundant bootstrap)
BOOTSTRAP_NODES=/ip4/{NODE0_IP}/udp/8041/quic-v1/p2p/{NODE0_PEER_ID},/ip4/{NODE1_IP}/udp/8041/quic-v1/p2p/{NODE1_PEER_ID}
NODE_PRIVATE_KEY=<key2>
NODE_WALLET_ADDRESS=<wallet2>
```

**Step 4 — Verify cluster**

```bash
# On each node, check logs for connections
docker-compose logs | grep "Connection established"

# Node 0 should see connections from Node 1 and Node 2
# Node 1 should see connections from Node 0 and Node 2
# Node 2 should see connections from Node 0 and Node 1

# Check that all three wallets are in the reputation table
docker-compose logs | grep "Added new node"
```

**Step 5 — End-to-end test**

```bash
# Register DID on Node 0
curl -X POST http://{NODE0_IP}:3000/did/register \
  -H "Content-Type: application/json" \
  -d '{"public_key":"0xtest"}'
# → {"did":"did:feedo:test"}

# Register name on Node 0 (requires valid signature in production)
# Test: resolve a known name from Node 2
curl http://{NODE2_IP}:3000/resolve/test.feedo

# Check DHT sync: register name on Node 0, resolve from Node 1 after 10s
```

### Adding a node to an existing cluster

1. Generate new `NODE_PRIVATE_KEY` (`openssl rand -hex 32`)
2. Set `NODE_WALLET_ADDRESS` to a new unique Ethereum address
3. Set `BOOTSTRAP_NODES` to 2+ existing node multiaddrs
4. Deploy and start. Node discovers peers via DHT within ~30 seconds.

### Removing a node

```bash
docker-compose -f docker-compose.consensus.yml stop
# Or: kubectl scale statefulset consensus-node --replicas=2
```

The Kademlia DHT automatically detects the node is gone. If the node was a committee member, the next epoch rotation will select a replacement. **No manual rebalancing needed.**

---

## 8. Networking Deep Dive

### Why UDP/QUIC

Consensus-node uses libp2p with **QUIC transport over UDP**. This is deliberate:
- **Multiplexed streams** — PBFT votes and DHT lookups share one port
- **No head-of-line blocking** — a lost packet in one PBFT vote doesn't block others
- **Better NAT traversal** — QUIC connection IDs survive IP changes
- **Mandatory encryption** — noise + QUIC TLS 1.3

### Bandwidth estimation

Compared to storage-node (which transfers megabyte shards), consensus traffic is tiny:

| Operation | Data per message | Messages per tx | Total per tx |
|-----------|-----------------|----------------|--------------|
| PBFT PrePrepare | ~400 bytes protobuf | 1 (leader) | 400 bytes |
| PBFT Prepare | ~500 bytes protobuf | 20 (committee - 1) | ~10 KB |
| PBFT Commit | ~500 bytes protobuf | 20 (committee - 1) | ~10 KB |
| PBFT Finalized | ~500 bytes protobuf | 20 (committee - 1) | ~10 KB |
| **Total per tx** | | | **~31 KB** |

At 10 transactions/minute → ~5 KB/s. At 100 tx/min → ~50 KB/s. A 10 Mbps link can handle ~2000+ tx/min — far beyond current needs.

### Cloud provider firewall setup

| Provider | How to open UDP 8041 |
|----------|---------------------|
| **Hetzner** | Cloud Console → Firewalls → Create firewall → Inbound rule: UDP, Port 8041, Source 0.0.0.0/0. Apply to server. |
| **AWS** | EC2 → Security Groups → Inbound rules → Custom UDP, Port 8041, Source 0.0.0.0/0 |
| **GCP** | VPC Network → Firewall → Create rule → Allow ingress, UDP:8041, Target: instance tag `feedo-consensus` |
| **DigitalOcean** | Networking → Firewalls → Create firewall → Inbound: UDP, Port 8041, All sources. Apply to Droplet. |

**Double check**: Cloud provider firewall + OS-level firewall (ufw/iptables). Both must allow UDP 8041.

---

## 9. Secrets Management

### Two critical secrets

| Secret | Type | Determines |
|--------|------|------------|
| `NODE_PRIVATE_KEY` | Ed25519 (64 hex) | P2P identity — your PeerId on the libp2p network |
| `NODE_WALLET_ADDRESS` | Ethereum (42 hex) | Committee identity — your identity for reputation scoring |

**Generation**:
```bash
# P2P identity key
openssl rand -hex 32
# → 64-character hex string

# Wallet address is your existing Ethereum address — no generation needed.
```

**Storage options** (ranked by security):

| Method | Security | Complexity | Best for |
|--------|----------|------------|----------|
| Docker secrets | High | Medium | Docker Swarm |
| Kubernetes Secrets | High | Medium | K8s clusters |
| Ansible Vault | High | Medium | Ansible-managed infra |
| HashiCorp Vault | Highest | High | Enterprise |
| `.env` with `chmod 600` | Medium | Low | Single node / small clusters |

### Key rotation

| Key | Can rotate? | Impact |
|-----|------------|--------|
| `NODE_PRIVATE_KEY` | **NO** | Changing it gives you a new PeerId. All nodes that knew your old PeerId must re-discover you. Your reputation in the committee is tied to `NODE_WALLET_ADDRESS`, not `NODE_PRIVATE_KEY`. |
| `NODE_WALLET_ADDRESS` | **NO** | Changing it resets your reputation to 10. Your old wallet's reputation is orphaned. Only change if wallet is compromised. |

### If key is compromised

- **`NODE_PRIVATE_KEY` compromised**: Attacker can impersonate your node on the P2P network. Generate new key, redeploy. Your reputation (tied to wallet) is unaffected.
- **`NODE_WALLET_ADDRESS` compromised**: You cannot change this without losing your reputation. This is why the wallet private key should be kept separate and offline.

---

## 10. Monitoring Stack

### Current built-in endpoints

```bash
# Name resolution (always responds — null if name not found)
curl http://localhost:3000/resolve/test.feedo

# DID balance (verifies ledger is working)
curl http://localhost:3000/did/did:feedo:test/balance
```

### Recommended: Prometheus + Grafana

**Prometheus scrape config** (`prometheus.yml`):

```yaml
scrape_configs:
  - job_name: 'feedo-consensus'
    scrape_interval: 30s
    static_configs:
      - targets:
          - 'node0:3000'
          - 'node1:3000'
          - 'node2:3000'
    metrics_path: '/resolve/test.feedo'
    # Note: /resolve returns JSON, not Prometheus format.
    # Use json_exporter or a custom sidecar to extract metrics.
```

**Node Exporter** (system metrics): CPU, RAM, disk I/O, network throughput. Install on every node:
```bash
sudo apt install prometheus-node-exporter
```

**Grafana dashboard panels:**

| Panel | Source | Type |
|-------|--------|------|
| Peer count | Log-based: count `Connection established` events | Stat |
| Committee size | Log-based: parse `[COMMITTEE] Selected N validators` | Gauge |
| In committee? | Compare `NODE_WALLET_ADDRESS` against committee log | Boolean |
| Current epoch | Log-based: parse `[EPOCH] Rotated to epoch N` | Gauge |
| Transaction rate | Log-based: count `FINALIZED` per minute | Graph |
| Reputation score | DHT record `/reputation/{wallet}` | Gauge |
| CPU usage | Node Exporter | Graph |
| RAM usage | Node Exporter | Graph |
| Disk usage | Node Exporter | Gauge |
| Network throughput | Node Exporter | Graph |

### Alerting rules (Prometheus AlertManager)

```yaml
groups:
  - name: feedo-consensus
    rules:
      - alert: ConsensusNodeDown
        expr: up{job="feedo-consensus"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Consensus node {{ $labels.instance }} is down"

      - alert: ConsensusNotInCommittee
        expr: feedo_consensus_in_committee == 0
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Node {{ $labels.instance }} is not in the validator committee"

      - alert: ConsensusEpochStalled
        expr: delta(feedo_consensus_epoch[15m]) == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Epoch has not changed in 15 minutes on {{ $labels.instance }}"

      - alert: ConsensusLowReputation
        expr: feedo_consensus_reputation < 10
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Node {{ $labels.instance }} reputation dropped below 10"

      - alert: DiskFull
        expr: node_filesystem_avail_bytes{mountpoint="/data"} / node_filesystem_size_bytes{mountpoint="/data"} < 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Data disk >90% full on {{ $labels.instance }}"
```

### Log aggregation with Loki + Promtail

Collect consensus-node logs and create alerts for:
- `Error dialing` → bootstrap node unreachable
- `Failed to fetch committee from contract` → Polygon RPC down
- `[PBFT_FALLBACK]` → no committee peers (Phase 1 fallback mode)

---

## 11. CI/CD Pipeline

### GitHub Actions — build, test, deploy

```yaml
name: Consensus Node CI/CD

on:
  push:
    branches: [main]
    paths:
      - 'microservices/consensus-node/**'
      - 'microservices/shared-proto/**'
  pull_request:
    paths:
      - 'microservices/consensus-node/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - name: Check compilation
        run: cargo check --manifest-path microservices/consensus-node/Cargo.toml
      - name: Run unit tests
        run: cargo test --manifest-path microservices/consensus-node/Cargo.toml --bin consensus-node

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
            cargo build --release --manifest-path microservices/consensus-node/Cargo.toml
            sudo systemctl restart feedo-consensus
            sleep 30
            curl -f http://localhost:3000/resolve/test.feedo || exit 1

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
            cargo build --release --manifest-path microservices/consensus-node/Cargo.toml
            sudo systemctl restart feedo-consensus
```

### Canary deployment strategy

1. Deploy to 1 node (canary)
2. Run health check (`curl /resolve/test.feedo`)
3. Verify peer connections restored (check logs for `Connection established`)
4. Wait 5 minutes — observe monitoring
5. Deploy to remaining nodes (rolling, one at a time)

### Rollback

```bash
# On each node
cd /opt/feedo
git checkout <previous-commit-sha>
cargo build --release --manifest-path microservices/consensus-node/Cargo.toml
sudo systemctl restart feedo-consensus
```

Docker-based rollback:
```bash
docker-compose -f docker-compose.consensus.yml pull consensus-node:<previous-tag>
docker-compose -f docker-compose.consensus.yml up -d
```

---

## 12. Production Hardening Checklist

Before going to production, verify every item:

- [ ] **Network**: UDP port 8041 open in cloud provider firewall AND OS firewall (ufw/iptables)
- [ ] **Network**: TCP port 3000 open only if external name API access is needed (restrict source IPs if possible)
- [ ] **Network**: TCP port 50051 NOT exposed (gRPC — internal only)
- [ ] **Identity**: `NODE_PRIVATE_KEY` generated, stored in secrets manager, backed up offline
- [ ] **Identity**: `NODE_WALLET_ADDRESS` set to your actual Ethereum address (not the default)
- [ ] **Storage**: `DB_DIR` on SSD volume, not root partition, XFS or ext4
- [ ] **Storage**: Disk space ≥ 20 GB (consensus data is small — this is generous)
- [ ] **Resources**: CPU/memory limits configured (Docker: `deploy.resources.limits`, systemd: `MemoryMax`/`CPUQuota`)
- [ ] **Resources**: `LimitNOFILE=65536` (consensus-node opens many concurrent P2P connections)
- [ ] **Logs**: Log rotation configured (Docker: `max-size`/`max-file`, systemd: journald `MaxRetentionSec`)
- [ ] **Logs**: `RUST_LOG=info` (not debug — debug generates gigabytes of P2P gossip logs per day)
- [ ] **Process**: Runs as non-root user (`User=feedo` in systemd, `user: "1000:1000"` in Docker)
- [ ] **Process**: Automatic restart on failure (`restart: unless-stopped` in Docker, `Restart=always` in systemd)
- [ ] **Bootstrap**: ≥2 redundant bootstrap nodes in `BOOTSTRAP_NODES` for follower nodes
- [ ] **Bootstrap**: `CONSENSUS_DIRECT_MODE=true` (Phase 1 direct messaging, recommended)
- [ ] **Blockchain**: `ETH_RPC_URL` uses a reliable endpoint (consider your own Infura/Alchemy key)
- [ ] **Monitoring**: Health endpoint scraped by Prometheus, alerts configured
- [ ] **Monitoring**: System metrics (CPU, RAM, disk, network) collected via Node Exporter
- [ ] **Backup**: `peer_key.bin` backed up to separate location (off-server)
- [ ] **CI/CD**: Automated tests pass before deploy, canary deployment before full rollout
- [ ] **Documentation**: Runbook exists — ops team knows how to diagnose (see Section 10 of Operator Guide)

### Quick verification script

```bash
#!/bin/bash
# Run on each node to verify production readiness
set -e

echo "=== Consensus Node Production Readiness Check ==="

# 1. Process running?
systemctl is-active feedo-consensus || docker ps | grep consensus-node || exit 1
echo "✅ Process running"

# 2. HTTP API responding?
curl -sf http://localhost:3000/resolve/test.feedo > /dev/null
echo "✅ HTTP API responding"

# 3. UDP port listening?
ss -uln | grep -q 8041
echo "✅ P2P port listening (UDP 8041)"

# 4. Disk space sufficient?
USAGE=$(df /data/feedo/consensus --output=pcent | tail -1 | tr -d ' %')
if [ "$USAGE" -lt 80 ]; then
    echo "✅ Disk usage ${USAGE}% (<80%)"
else
    echo "⚠️  Disk usage ${USAGE}% — consider expanding"
fi

# 5. Peers connected? (check logs last 5 min)
PEERS=$(journalctl -u feedo-consensus --since "5 min ago" 2>/dev/null | grep -c "Connection established" || \
        docker logs --since 5m feedo-consensus 2>&1 | grep -c "Connection established" || echo "0")
echo "✅ Peers connected in last 5 min: $PEERS"

# 6. Recent epoch rotation?
EPOCH=$(journalctl -u feedo-consensus --since "15 min ago" 2>/dev/null | grep -c "Rotated to epoch" || \
        docker logs --since 15m feedo-consensus 2>&1 | grep -c "Rotated to epoch" || echo "0")
echo "ℹ️  Epoch rotations in last 15 min: $EPOCH"

echo "=== All checks passed ==="
```

---

## Additional Resources

- [CONSENSUS_OPERATOR.md](./CONSENSUS_OPERATOR.md) — Single-node operations, troubleshooting
- [CONSENSUS_DOCS.md](./CONSENSUS_DOCS.md) — Architecture, API reference, protocol internals
- [CONSENSUS_ROADMAP.md](./CONSENSUS_ROADMAP.md) — 4-phase scaling plan
- [Main project README](../../README.md) — Feedo ecosystem overview