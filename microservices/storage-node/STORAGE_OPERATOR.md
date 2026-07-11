# Storage Node — Operator Guide

> **Audience**: Node operators who want to run a Feedo storage node.
> **Prerequisite knowledge**: Basic Linux administration, Docker, command line.
> For architecture and API details, see [STORAGE_DOCS.md](./STORAGE_DOCS.md).

---

## 1. Prerequisites

### Hardware

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 2 GB | 4 GB+ |
| Disk | SSD, free space ≥ your configured quotas | Enterprise SSD |
| Network | 10 Mbps, static public IP | 100+ Mbps |

**Disk sizing formula**: `SUM(all quotas) × 1.5`. The 50% overhead accounts for Reed-Solomon parity shards and Sled database metadata. Example: quotas totalling 1.1 TB → provision ~1.7 TB.

### Software

- **Docker** + Docker Compose (recommended) — simplest deployment
- **Rust toolchain** (alternative) — `rustup` with stable channel, edition 2024
- **Linux** (Ubuntu 22.04+ or Debian 12+ recommended). macOS works for testing.

### Network

| Port | Protocol | Required | Purpose |
|------|----------|----------|---------|
| `P2P_PORT` (8040) | UDP | **Yes** | libp2p QUIC — peer discovery, shard transfer |
| `HTTP_PORT` (3001) | TCP | Optional (external) | REST API for upload/download/quota |
| `GRPC_PORT` (50052) | TCP | **No** (internal) | gRPC for inter-service communication |

Your node MUST have a publicly reachable UDP port for P2P communication. Without it, other peers cannot send shards to your node.

---

## 2. Quick Start (Docker)

### Step 1: Create `.env` file

```bash
# === Storage Node ===
DB_DIR=storage_db
HTTP_PORT=3001
GRPC_PORT=50052
P2P_PORT=8040
BOOTSTRAP_NODES=
RUST_LOG=info

# === Phase 1 Quotas ===
QUOTA_SITES_GB=100
QUOTA_BLOBS_GB=1000
QUOTA_SOCIAL_MB=500
QUOTA_PROFILES_MB=100
```

### Step 2: Start the node

```bash
docker-compose up -d storage-node
```

### Step 3: Verify it's running

```bash
# Check quota endpoint (should return JSON with all 4 classes)
curl http://localhost:3001/api/v1/quota

# Check logs for peer discovery
docker-compose logs -f storage-node | grep -E "peer id:|Listening on|Connection established"
```

You should see:
```
Local peer id: PeerId("12D3KooW...")
Listening on P2P address: /ip4/0.0.0.0/udp/8040/quic-v1
```

### Step 4: Upload a test file

```bash
echo "Hello Feedo!" > test.txt
curl -X POST http://localhost:3001/upload \
  -H "X-Feedo-Storage-Class: blob" \
  -F "file=@test.txt"
# → returns a SHA256 hex hash
```

---

## 3. Building from Source

### Install Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup update stable
```

### Build

```bash
git clone https://github.com/Ashixi/feedo.git
cd feedo
cargo build --release --manifest-path microservices/storage-node/Cargo.toml
```

Binary location: `microservices/target/release/storage-node`

### Run

```bash
export DB_DIR=/data/feedo/storage
export HTTP_PORT=3001
export GRPC_PORT=50052
export P2P_PORT=8040
export BOOTSTRAP_NODES=""
export QUOTA_SITES_GB=100
export QUOTA_BLOBS_GB=1000
export QUOTA_SOCIAL_MB=500
export QUOTA_PROFILES_MB=100
export RUST_LOG=info

./microservices/target/release/storage-node
```

### systemd unit file (production)

Create `/etc/systemd/system/feedo-storage.service`:

```ini
[Unit]
Description=Feedo Storage Node
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=feedo
WorkingDirectory=/opt/feedo
EnvironmentFile=/opt/feedo/.env
ExecStart=/opt/feedo/storage-node
Restart=always
RestartSec=10
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now feedo-storage
sudo journalctl -u feedo-storage -f
```

---

## 4. Configuration Reference

All configuration via environment variables. Set these in your `.env` file or Docker Compose `environment` section.

| Variable | Type | Default | When to change |
|----------|------|---------|----------------|
| `DB_DIR` | path | `storage_db` | Point to a dedicated SSD mount, e.g. `/data/feedo/storage` |
| `HTTP_PORT` | u16 | `3001` | If port 3001 is already in use |
| `GRPC_PORT` | u16 | `50052` | Only if port conflict with another gRPC service |
| `P2P_PORT` | u16 | `8040` | **Must be open on firewall** — change if your provider blocks UDP/8040 |
| `BOOTSTRAP_NODES` | string | (empty) | Comma-separated multiaddrs of existing nodes to join the network. Leave empty to start a new network. |
| `NODE_PRIVATE_KEY` | hex | auto-gen | **Optional** — auto-generated and saved to `peer_key.bin` if not set. Only set explicitly if migrating to a new server, using IaC (Ansible/Terraform), or storing in a secrets manager. 64-char Ed25519 hex. |
| `DHT_RAM_CACHE_LIMIT` | usize | `1000` | Reduce to `500` if your node has <2 GB RAM. Increase to `5000` for better DHT performance. |
| `RUST_LOG` | string | — | `info` for normal operation, `debug` for troubleshooting, `info,storage_node=debug` for storage-specific detail |
| `QUOTA_SITES_GB` | f64 | `100` | Max gigabytes for websites. **Highest priority** — never evicted. |
| `QUOTA_BLOBS_GB` | f64 | `1000` | Max gigabytes for generic files/cloud storage. |
| `QUOTA_SOCIAL_MB` | f64 | `500` | Max megabytes for Nostr social posts. **Lowest priority** — temporary data. |
| `QUOTA_PROFILES_MB` | f64 | `100` | Max megabytes for Nostr user profiles. |

**Storage class priority** (what gets accepted when disk is close to full):
1. `Site` — highest, indefinite storage
2. `Profile` — medium
3. `Blob` — medium (paid via tokenomics in future)
4. `SocialPost` — lowest, temporary (30-day TTL planned)

**Floating-point quotas** are supported: `QUOTA_SOCIAL_MB=0.5` = 512 KB.

**Wallet/identity variables** (important distinction):

| Variable | Type | Used by storage-node? | Purpose |
|----------|------|:---:|---------|
| `NODE_PRIVATE_KEY` | Ed25519 (64 hex) | ✅ Yes | P2P identity (libp2p PeerId). **Auto-generated** if not set — saved to `{DB_DIR}/peer_key.bin`. Only set explicitly for key migration or IaC. |
| `NODE_WALLET_ADDRESS` | Ethereum address (42 hex) | 🔜 Future (Phase 5) | Address for Proof-of-Storage rewards. Set it now — not used yet, but will be when tokenomics are integrated. |
| `NODE_WALLET_PRIVATE_KEY` | Ethereum (64 hex) | ❌ No | Used only by consensus-node for signing on-chain transactions. Storage-node **never reads** this variable. |

`NODE_PRIVATE_KEY` (Ed25519) and `NODE_WALLET_PRIVATE_KEY` (Ethereum) are **different keys** for **different services**. They have similar names but serve completely different purposes.

---

## 5. First Node vs Joining an Existing Network

### Starting a new network (genesis node)

Set `BOOTSTRAP_NODES=` (empty). Your node creates a new Kademlia DHT and becomes the first peer. Other nodes will join by specifying your multiaddr as their bootstrap node.

### Joining an existing network

Set `BOOTSTRAP_NODES` to the multiaddr of at least one existing node.

**Format**: `/ip4/{PUBLIC_IP}/udp/{P2P_PORT}/quic-v1/p2p/{PEER_ID}`

**Example** (real Feedo bootstrap nodes):
```bash
# Two redundant bootstrap nodes:
BOOTSTRAP_NODES=/ip4/95.111.245.68/udp/8040/quic-v1/p2p/12D3KooWEqk8NVx5WnGPCA6ybgifRZVaNNFLRqHBrH1xGbab5tb6,/ip4/178.18.253.94/udp/8040/quic-v1/p2p/12D3KooWBWEUuGg2dGQM7U1zsyXguyjWMF8ZWwZsQ5VNPxKMwyRg
```

**Current Feedo network bootstrap nodes:**

| Node | IP | Port | PeerId |
|------|----|------|--------|
| Node 1 | 95.111.245.68 | 8040 | `12D3KooWEqk8NVx5WnGPCA6ybgifRZVaNNFLRqHBrH1xGbab5tb6` |
| Node 2 | 178.18.253.94 | 8040 | `12D3KooWBWEUuGg2dGQM7U1zsyXguyjWMF8ZWwZsQ5VNPxKMwyRg` |

```bash
# Connect to the Feedo storage network:
BOOTSTRAP_NODES=/ip4/95.111.245.68/udp/8040/quic-v1/p2p/12D3KooWEqk8NVx5WnGPCA6ybgifRZVaNNFLRqHBrH1xGbab5tb6,/ip4/178.18.253.94/udp/8040/quic-v1/p2p/12D3KooWBWEUuGg2dGQM7U1zsyXguyjWMF8ZWwZsQ5VNPxKMwyRg
```

The node tries each in order and starts serving as soon as it connects to at least one.

---

## 6. Quota Planning Guide

Choose quotas based on your node's role. The sum of all quotas is the maximum disk space your node will use.

### Role templates

| Role | QUOTA_SITES_GB | QUOTA_BLOBS_GB | QUOTA_SOCIAL_MB | QUOTA_PROFILES_MB | Total (~) |
|------|---------------|---------------|-----------------|-------------------|-----------|
| **Website host** | 500 | 100 | 100 | 50 | 600 GB |
| **Social archiver** | 10 | 50 | 5000 | 500 | 65 GB |
| **Cloud storage** | 50 | 5000 | 100 | 50 | 5.05 TB |
| **Balanced** (default) | 100 | 1000 | 500 | 100 | 1.1 TB |
| **Minimal** (low-resource) | 10 | 100 | 100 | 20 | 110 GB |

### What happens when a quota is full

- The node returns **HTTP 507 Insufficient Storage** for uploads of that class
- Other storage classes continue working normally
- A warning is printed to stderr: `[Quota] WARNING: Storage quota exceeded for class 'social_post': 500.00 MB used of 500.00 MB max`
- The node does **not** shut down or reject all traffic

### Increasing quotas later

1. Update the env var in `.env` or Docker Compose
2. Restart the node
3. Existing data is preserved — only the limit changes

---

## 7. Monitoring & Health Checks

### Built-in health endpoints

```bash
# Per-class quota usage (always returns 200)
curl http://localhost:3001/api/v1/quota

# Recent upload hashes (in-memory, lost on restart)
curl http://localhost:3001/api/files/recent

# Download a known file to verify data availability
curl http://localhost:3001/download/{hash}
```

### Log-based health indicators

| Log message | What it means |
|-------------|--------------|
| `Local peer id: PeerId("...")` | Node started successfully with its identity |
| `Listening on P2P address:` | P2P port is bound and listening |
| `Connection established with` | Successfully connected to a peer |
| `Dialing bootstrap node:` | Attempting to connect to a bootstrap node |
| `Kademlia DHT discovered a new node:` | A new peer was found via DHT routing |
| `[Quota] Sites: 100 GB, Blobs: 1000 GB, ...` | Quota manager initialised with configured values |
| `[Quota] WARNING:` | A storage class quota has been exceeded |

### Warning signs

| Symptom | Likely issue |
|---------|-------------|
| No `Connection established` for 5+ minutes after start | Bootstrap node unreachable, firewall blocking UDP, or wrong multiaddr |
| No `Kademlia DHT discovered a new node` for 30+ minutes | Node is isolated — check `P2P_PORT` is open on firewall |
| Repeated `Error dialing` | Bootstrap node offline or invalid multiaddr |
| `[Quota] WARNING:` appearing frequently | Increase quotas or reduce upload rate |

### Prometheus / Grafana

Not yet built-in (planned for Phase 5). For now, use `curl` + cron for basic monitoring:

```bash
# Check quota every 5 minutes, alert if any class is >90% full
*/5 * * * * curl -s http://localhost:3001/api/v1/quota | jq '.[] | select(.used_bytes / .max_bytes > 0.9)'
```

---

## 8. Storage Management

### Where data lives

| Path | Content | Safe to delete? |
|------|---------|-----------------|
| `{DB_DIR}/` | Sled database — all Kademlia records (shards + manifests) | Yes, but you lose all locally stored shards |
| `{DB_DIR}/peer_key.bin` | Node identity (Ed25519 keypair) | **NO** — back this up |
| `peer_cache.json` | Known peers list (scored) | Yes — node will re-discover peers |

### Check database size

```bash
du -sh storage_db/
# Example output: 45G   storage_db/
```

### Backup

**Critical**: Back up `{DB_DIR}/peer_key.bin`. This file contains your node's Ed25519 private key. If lost, your node gets a new PeerId and all existing shard references to the old PeerId become invalid.

```bash
cp storage_db/peer_key.bin ~/backups/peer_key_$(date +%Y%m%d).bin
```

### Reset (factory reset)

```bash
# Stop the node
docker-compose stop storage-node
# Or: sudo systemctl stop feedo-storage

# Backup peer key first
cp storage_db/peer_key.bin ~/backups/

# Remove database (all local shards are lost — network will rebalance)
rm -rf storage_db/

# Restore peer key to keep same identity
mkdir storage_db
cp ~/backups/peer_key.bin storage_db/

# Restart
docker-compose up -d storage-node
```

### Peer cache maintenance

```bash
# View peer cache
cat peer_cache.json | jq .

# Reset peer cache (force re-discovery)
rm peer_cache.json
# Node will repopulate from Kademlia routing table and gossipsub announces
```

---

## 9. Firewall Configuration

### Required: open UDP for P2P

```bash
# ufw (Ubuntu/Debian)
sudo ufw allow 8040/udp
sudo ufw enable

# firewalld (RHEL/CentOS/Fedora)
sudo firewall-cmd --permanent --add-port=8040/udp
sudo firewall-cmd --reload

# iptables (generic)
sudo iptables -A INPUT -p udp --dport 8040 -j ACCEPT
sudo iptables-save > /etc/iptables/rules.v4
```

### Optional: open TCP for HTTP API

Only if you want external clients to use your node's REST API directly:

```bash
sudo ufw allow 3001/tcp
```

### DO NOT expose

- `GRPC_PORT` (50052) — internal service communication only
- `P2P_PORT` via TCP — the node uses QUIC (UDP), not TCP, for P2P

### Verify port is reachable

From another machine:
```bash
nc -u -z YOUR_SERVER_IP 8040 && echo "UDP OPEN" || echo "UDP CLOSED"
```

If using a cloud provider (AWS, GCP, DigitalOcean), also open the port in the **security group / firewall rules** in the provider's console.

---

## 10. Troubleshooting

| Symptom | Likely cause | Solution |
|---------|-------------|----------|
| Node starts but no peers connect | UDP port blocked by firewall | Open `P2P_PORT` (default 8040) for UDP in firewall AND cloud provider security group |
| `Error dialing` in logs | Bootstrap node offline or wrong multiaddr | Verify bootstrap node is running: check its logs. Try alternative bootstrap nodes. |
| 507 Insufficient Storage on upload | Quota for that storage class is full | Increase corresponding `QUOTA_*` env var and restart; or free space by deleting old data |
| Download returns 404 | File manifest lost or insufficient shards | Manifest stored with `Quorum::One` (Phase 1). Try again later — another node may have a copy. Phase 3 will add redundancy. |
| `Sled` IO errors | Disk full or filesystem corruption | Check `df -h`. If disk is fine, stop node, remove `DB_DIR`, restart (network will rebalance shards). |
| `cargo build` fails | Wrong Rust version | `rustup update stable`. Project requires edition 2024. |
| Node uses too much RAM | DHT cache too large for available memory | Reduce `DHT_RAM_CACHE_LIMIT` (e.g. to `500` or `200`) |
| "Failed to decode peer_key.bin" | Corrupt key file | Restore from backup. If no backup: delete `peer_key.bin` — node will generate new identity (existing shard references become invalid). |
| High CPU after start | Normal — initial DHT bootstrapping | Wait 5-10 minutes. CPU usage should drop once routing table is populated. |
| `AlreadyExists` or `MaxProvidedKeys` errors | Kademlia store limit reached for a key (rare) | Increase `DHT_RAM_CACHE_LIMIT`. These are usually transient and self-resolving. |

### Gathering debug info

```bash
# Full logs with storage-specific debug
RUST_LOG=debug cargo run --manifest-path microservices/storage-node/Cargo.toml 2>&1 | tee storage-debug.log

# Check open ports
ss -tuln | grep -E "3001|8040|50052"

# Check disk usage
df -h $(pwd)/storage_db
du -sh storage_db/
```

---

## 11. Upgrading

### Docker

```bash
# Pull latest image
docker-compose pull storage-node

# Restart
docker-compose up -d storage-node

# Verify
curl http://localhost:3001/api/v1/quota
```

### From source

```bash
git pull
cargo build --release --manifest-path microservices/storage-node/Cargo.toml
sudo systemctl restart feedo-storage
sudo journalctl -u feedo-storage -f
```

### Before upgrading

1. **Back up `peer_key.bin`**: `cp {DB_DIR}/peer_key.bin ~/backups/`
2. **Check current version**: `grep '^version' microservices/storage-node/Cargo.toml`
3. **Review release notes**: check commit history for breaking changes
4. **Plan for 30-60 seconds downtime** (normal restart time)

### Compatibility notes

| Change | Backward compatible? |
|--------|---------------------|
| Manifest v1 → v2 (Phase 1) | ✅ Yes — `storage_class` is `Option<String>` |
| New env vars (Phase 1 quotas) | ✅ Yes — have defaults |
| Future: Manifest v3 (Phase 2) | Will be backward compatible |
| Future: Quorum::Three manifests (Phase 3) | Breaking — but only for new uploads, old manifests still readable |

---

## Additional Resources

- [STORAGE_DOCS.md](./STORAGE_DOCS.md) — Architecture, API reference, protocol details (for developers)
- [STORAGE_ROADMAP.md](./STORAGE_ROADMAP.md) — 5-phase scaling plan
- [Main project README](../../README.md) — Feedo ecosystem overview