# Consensus Node — Operator Guide

> **Audience**: Node operators who want to run a Feedo consensus/validator node.
> **Prerequisite knowledge**: Basic Linux administration, Docker, command line.
> For architecture and API details, see [CONSENSUS_DOCS.md](./CONSENSUS_DOCS.md).

---

## 1. Prerequisites

### Hardware

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 2 GB | 4 GB+ |
| Disk | SSD, 20 GB | SSD, 40 GB+ |
| Network | 10 Mbps, static public IP | 100+ Mbps |

Disk usage grows slowly — name registrations and ledger entries are small records (SQLite + Sled). After Phase 1.5, storage is bounded (~10-20 MB per node regardless of network age).

### Software

- **Docker** + Docker Compose (recommended) — simplest deployment
- **Rust toolchain** (alternative) — `rustup` with stable channel, edition 2024
- **Linux** (Ubuntu 22.04+ or Debian 12+ recommended). macOS works for testing.

### Network

| Port | Protocol | Required | Purpose |
|------|----------|----------|---------|
| `P2P_PORT` (8041) | UDP | **Yes** | libp2p QUIC — peer discovery, PBFT vote relay |
| `HTTP_PORT` (3000) | TCP | Optional (external) | REST API for name registration/resolve |
| `GRPC_PORT` (50051) | TCP | **No** (internal) | gRPC for inter-service communication |

Your node MUST have a publicly reachable UDP port for P2P communication. Without it, other validators cannot send PBFT votes to your node and you cannot participate in consensus.

---

## 2. Quick Start (Docker)

### Step 1: Create `.env` file

```bash
# === Consensus Node ===
DB_DIR=consensus_db
HTTP_PORT=3000
GRPC_PORT=50051
P2P_PORT=8041
BOOTSTRAP_NODES=
NODE_WALLET_ADDRESS=0x0000000000000000000000000000000000000000
EPOCH_DURATION_SECS=600
CONSENSUS_DIRECT_MODE=true
ETH_RPC_URL=https://polygon-rpc.com
RUST_LOG=info
```

### Step 2: Start the node

```bash
docker-compose up -d consensus-node
```

### Step 3: Verify it's running

```bash
# Check that the HTTP API responds (returns null if name not found — normal for fresh node)
curl http://localhost:3000/resolve/test.feedo

# Check logs for peer discovery
docker-compose logs -f consensus-node | grep -E "peer id:|Listening on|Connection established"
```

You should see:
```
Consensus Local peer id: PeerId("12D3KooW...")
Consensus node listening on P2P address: /ip4/0.0.0.0/udp/8041/quic-v1
Node Wallet Address (committee identity): 0x...
```

### Step 4: Register a DID and name

```bash
# 1. Register a DID (generates an identifier, credits 500,000)
curl -X POST http://localhost:3000/did/register \
  -H "Content-Type: application/json" \
  -d '{"public_key":"0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
# → {"did":"did:feedo:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}

# 2. Check balance
curl http://localhost:3000/did/did:feedo:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/balance
# → {"balance_credits":500000}
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
cargo build --release --manifest-path microservices/consensus-node/Cargo.toml
```

Binary location: `microservices/target/release/consensus-node`

### Run

```bash
export DB_DIR=/data/feedo/consensus
export HTTP_PORT=3000
export GRPC_PORT=50051
export P2P_PORT=8041
export BOOTSTRAP_NODES=""
export NODE_WALLET_ADDRESS=0xYourEthereumAddressHere
export EPOCH_DURATION_SECS=600
export CONSENSUS_DIRECT_MODE=true
export ETH_RPC_URL=https://polygon-rpc.com
export RUST_LOG=info

./microservices/target/release/consensus-node
```

### systemd unit file (production)

Create `/etc/systemd/system/feedo-consensus.service`:

```ini
[Unit]
Description=Feedo Consensus Node
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=feedo
WorkingDirectory=/opt/feedo
EnvironmentFile=/opt/feedo/.env
ExecStart=/opt/feedo/consensus-node
Restart=always
RestartSec=10
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now feedo-consensus
sudo journalctl -u feedo-consensus -f
```

---

## 4. Configuration Reference

All configuration via environment variables. Set these in your `.env` file or Docker Compose `environment` section.

| Variable | Type | Default | When to change |
|----------|------|---------|----------------|
| `HTTP_PORT` | u16 | `3000` | If port 3000 is already in use |
| `GRPC_PORT` | u16 | `50051` | Only if port conflict with another gRPC service. Do NOT expose externally. |
| `P2P_PORT` | u16 | `8041` | **Must be open on firewall** — change if your provider blocks UDP/8041 |
| `DB_DIR` | path | `consensus_db` | Point to a dedicated SSD mount, e.g. `/data/feedo/consensus` |
| `NODE_WALLET_ADDRESS` | 42-char hex | `0x00...00` | Your Ethereum wallet address — used as your identity in the validator committee. Change before first start. |
| `NODE_PRIVATE_KEY` | 64-char hex | auto-gen | **Optional** — auto-generated and saved to `{DB_DIR}/peer_key.bin` if not set. Only set explicitly for key migration or IaC. 64-char Ed25519 hex. |
| `EPOCH_DURATION_SECS` | u64 | `600` | 600 (10 min) for production. Use `10` for testing to speed up epoch rotation. |
| `BOOTSTRAP_NODES` | string | (empty) | Comma-separated multiaddrs of existing nodes to join the network. Leave empty to start a new network. |
| `CONSENSUS_DIRECT_MODE` | bool | `true` | Phase 1: send PBFT votes via direct request-response instead of gossipsub. Keep `true` unless debugging. |
| `ETH_RPC_URL` | string | `https://polygon-rpc.com` | Polygon RPC endpoint for reading on-chain committee. Can use any Polygon RPC provider. |
| `RUST_LOG` | string | — | `info` for normal operation, `debug` for troubleshooting |

**Key identity variables** (important distinction):

| Variable | Type | Used by consensus-node? | Purpose |
|----------|------|:---:|---------|
| `NODE_PRIVATE_KEY` | Ed25519 (64 hex) | ✅ Yes | P2P identity (libp2p PeerId). **Auto-generated** if not set — saved to `{DB_DIR}/peer_key.bin`. Only set explicitly for key migration or IaC. |
| `NODE_WALLET_ADDRESS` | Ethereum address (42 hex) | ✅ Yes | Your identity in the validator committee. Used for reputation scoring and committee selection. Set this to your actual wallet address. |
| `NODE_WALLET_PRIVATE_KEY` | Ethereum (64 hex) | ❌ No | Used only by the auto-claim daemon for on-chain transactions. Consensus-node **never reads** this variable for core operations. |

`NODE_PRIVATE_KEY` (Ed25519) and `NODE_WALLET_PRIVATE_KEY` (Ethereum) are **different keys** for **different services**. They have similar names but serve completely different purposes.

---

## 5. First Node vs Joining an Existing Network

### Starting a new network (genesis node)

Set `BOOTSTRAP_NODES=` (empty). Your node creates a new Kademlia DHT and becomes the first peer. As the only validator, it operates with a self-only committee until other nodes join.

### Joining an existing network

Set `BOOTSTRAP_NODES` to the multiaddr of at least one existing node.

**Format**: `/ip4/{PUBLIC_IP}/udp/{P2P_PORT}/quic-v1/p2p/{PEER_ID}`

**How to find a node's PeerId**: Check its logs:
```
Consensus Local peer id: PeerId("12D3KooW...")
```

**Example** (connecting to a known consensus node):
```bash
BOOTSTRAP_NODES=/ip4/95.111.245.68/udp/8041/quic-v1/p2p/12D3KooWEqk8NVx5WnGPCA6ybgifRZVaNNFLRqHBrH1xGbab5tb6
```

**Note**: Feedo's public consensus network is still in early stages. The nodes listed in storage-node operator guide are storage nodes (port 8040), NOT consensus nodes (port 8041). Ensure you're connecting to the correct service.

The node tries each bootstrap address in order and starts serving as soon as it connects to at least one.

---

## 6. Committee & Consensus Operations

### How the committee works

- **Size**: Up to 21 validators, reputation-weighted selection
- **Selection**: Every epoch, validators are ranked by `hash(seed || wallet_address) × reputation`. Top 21 form the committee.
- **Reputation**: Earned by voting (Prepare=+1, Commit=+2). Lost by timeouts (-3) or invalid signatures (-5). Minimum score is 1.
- **Your role**: If your `NODE_WALLET_ADDRESS` is in the top-21, your node votes on PBFT consensus. If not, your node still participates in the network (DHT storage, transaction relay) but doesn't vote.

### Epoch rotation

Every `EPOCH_DURATION_SECS` (default: 10 minutes):
1. Committee is re-elected
2. A state snapshot is generated and published to DHT (`/snapshot/{epoch}`)
3. Old finalized transaction states are garbage-collected
4. All known names are re-published to DHT with the new epoch

The epoch tick runs every 5 seconds independently of transaction traffic — epoch rotation is guaranteed even during quiet periods.

### Phase 1: Direct consensus messaging

When `CONSENSUS_DIRECT_MODE=true` (default), PBFT votes go via direct libp2p request-response between committee validators. This replaces the old gossipsub flood model and reduces network overhead from O(n²) to O(committee_size). Gossipsub remains active for peer discovery and backward compatibility.

### What to do if your node is not in the committee

Nothing — this is normal. As more validators join the network, only the top-21 by reputation are selected. Your node still:
- Stores and serves DHT records (name resolutions)
- Relays transactions to committee members
- Accumulates reputation for future committee eligibility
- Generates and publishes state snapshots

---

## 7. Monitoring & Health Checks

### Built-in health endpoints

```bash
# Resolve a name (returns null if not found — normal for fresh node)
curl http://localhost:3000/resolve/test.feedo

# Check a DID balance (verifies ledger is working)
curl http://localhost:3000/did/did:feedo:aaaa...aaaa/balance

# Register a test DID (verifies full write path)
curl -X POST http://localhost:3000/did/register \
  -H "Content-Type: application/json" \
  -d '{"public_key":"0xtest"}'
```

### Log-based health indicators

| Log message | What it means |
|-------------|--------------|
| `Consensus Local peer id: PeerId("...")` | Node started successfully with its P2P identity |
| `Consensus node listening on P2P address:` | P2P port is bound and listening |
| `Consensus connected to` | Successfully connected to a peer |
| `[BOOTSTRAP] Published self-announce` | Node announced itself on gossipsub for discovery |
| `Dialing bootstrap node:` | Attempting to connect to a bootstrap node |
| `[EPOCH] Rotated to epoch N` | Epoch rotation successful — committee re-elected |
| `[SNAPSHOT] Published snapshot epoch=N` | State snapshot generated and published to DHT |
| `[PBFT_DIRECT] Sent Prepare to N peers` | PBFT vote sent via direct request-response (Phase 1) |
| `Decentralized Name FINALIZED:` | A name registration was finalized by consensus |
| `[COMMITTEE] Selected N validators` | Committee re-elected with N members |

### Warning signs

| Symptom | Likely issue |
|---------|-------------|
| No `Connection established` for 5+ minutes after start | Bootstrap node unreachable, firewall blocking UDP 8041, or wrong multiaddr |
| No `Kademlia DHT discovered a new node` for 30+ minutes | Node is isolated — check `P2P_PORT` is open on firewall |
| Repeated `Error dialing` | Bootstrap node offline or invalid multiaddr |
| `Failed to fetch committee from contract` | Polygon RPC unreachable (expected in test/dev — node uses self-only committee) |
| `[PBFT_FALLBACK] No committee peers known` | Self-only committee — normal for small networks. Will resolve when more validators join. |
| No `[EPOCH] Rotated` for 15+ minutes | No transactions triggering `handle_message()` — epoch tick will still rotate proactively every 5s check |

---

## 8. Database Management

### Where data lives

| Path | Content | Safe to delete? |
|------|---------|-----------------|
| `{DB_DIR}/sled/` | Sled database — DID documents, ledger balances | Yes, but you lose local DID/balance cache |
| `{DB_DIR}/names.db` | SQLite database — registered names with metadata | Yes, but names need to be re-synced from DHT |
| `{DB_DIR}/peer_key.bin` | Node identity (Ed25519 keypair) | **NO** — back this up |

### Check database size

```bash
du -sh consensus_db/
# Example output: 12M   consensus_db/
```

Consensus-node database is small (typically 10-20 MB) because it only stores current state, not transaction history. After Phase 1.5, size is bounded regardless of network age.

### Backup

**Critical**: Back up `{DB_DIR}/peer_key.bin`. This file contains your node's Ed25519 private key. If lost, your node gets a new PeerId and other nodes will see it as a completely new peer.

```bash
cp consensus_db/peer_key.bin ~/backups/peer_key_$(date +%Y%m%d).bin
cp consensus_db/names.db ~/backups/names_$(date +%Y%m%d).db
```

### Reset (factory reset)

```bash
# Stop the node
sudo systemctl stop feedo-consensus

# Backup peer key first
cp consensus_db/peer_key.bin ~/backups/

# Remove database (local state is lost — will re-sync from DHT)
rm -rf consensus_db/sled/ consensus_db/names.db

# Restore peer key to keep same identity
# (peer_key.bin was not deleted above, but if you deleted the whole DB_DIR:)
mkdir -p consensus_db
cp ~/backups/peer_key.bin consensus_db/

# Restart
sudo systemctl start feedo-consensus
```

---

## 9. Firewall Configuration

### Required: open UDP for P2P

```bash
# ufw (Ubuntu/Debian)
sudo ufw allow 8041/udp
sudo ufw enable

# firewalld (RHEL/CentOS/Fedora)
sudo firewall-cmd --permanent --add-port=8041/udp
sudo firewall-cmd --reload

# iptables (generic)
sudo iptables -A INPUT -p udp --dport 8041 -j ACCEPT
sudo iptables-save > /etc/iptables/rules.v4
```

### Optional: open TCP for HTTP API

Only if you want external clients to use your node's REST API directly:

```bash
sudo ufw allow 3000/tcp
```

### DO NOT expose

- `GRPC_PORT` (50051) — internal service communication only. Keep behind firewall.

### Verify port is reachable

From another machine:
```bash
nc -u -z YOUR_SERVER_IP 8041 && echo "UDP OPEN" || echo "UDP CLOSED"
```

If using a cloud provider (AWS, GCP, DigitalOcean, Hetzner), also open the port in the **security group / firewall rules** in the provider's console.

---

## 10. Troubleshooting

| Symptom | Likely cause | Solution |
|---------|-------------|----------|
| Node starts but no peers connect | UDP port blocked by firewall | Open `P2P_PORT` (default 8041) for UDP in firewall AND cloud provider security group |
| `Error dialing` in logs | Bootstrap node offline or wrong multiaddr | Verify bootstrap node is running: check its logs. Try alternative bootstrap nodes. |
| Name registration returns "Invalid signature" | Wrong signature format or wrong key | Ensure signature is hex-encoded with `0x` prefix. Verify the public key matches the DID. |
| Name registration returns "Insufficient credits" | DID has no balance | Register a DID first (gives 500,000 free credits). Check balance with `/did/:did/balance`. |
| Name registration returns "DID not found" | DID not registered or not synced | Register the DID first. If DID was registered on another node, wait for DHT sync (30-60 seconds). |
| `Failed to fetch committee from contract` at startup | Polygon RPC unreachable | Expected in test/dev — node falls back to self-only committee. For production, check `ETH_RPC_URL` is reachable. |
| `[PBFT_FALLBACK] No committee peers known` | Self-only committee | Normal for small networks. Will resolve when more validators join and discover each other. |
| `cargo build` fails | Wrong Rust version | `rustup update stable`. Project requires edition 2024. |
| "Failed to decode peer_key.bin" | Corrupt key file | Restore from backup. If no backup: delete `peer_key.bin` — node will generate new identity (you'll appear as a new peer on the network). |
| High CPU after start | Normal — initial DHT bootstrapping | Wait 5-10 minutes. CPU usage should drop once routing table is populated. |

### Gathering debug info

```bash
# Full logs with consensus-specific debug
RUST_LOG=debug cargo run --manifest-path microservices/consensus-node/Cargo.toml 2>&1 | tee consensus-debug.log

# Check open ports
ss -tuln | grep -E "3000|8041|50051"

# Check disk usage
df -h $(pwd)/consensus_db
du -sh consensus_db/

# Check if P2P port is listening
ss -uln | grep 8041
```

---

## 11. Upgrading

### Docker

```bash
# Pull latest image
docker-compose pull consensus-node

# Restart
docker-compose up -d consensus-node

# Verify
curl http://localhost:3000/resolve/test.feedo
```

### From source

```bash
git pull
cargo build --release --manifest-path microservices/consensus-node/Cargo.toml
sudo systemctl restart feedo-consensus
sudo journalctl -u feedo-consensus -f
```

### Before upgrading

1. **Back up `peer_key.bin`**: `cp {DB_DIR}/peer_key.bin ~/backups/`
2. **Check current version**: `grep '^version' microservices/consensus-node/Cargo.toml`
3. **Review release notes**: check commit history for breaking changes
4. **Plan for 30-60 seconds downtime** (normal restart time)

### Compatibility notes

| Change | Backward compatible? |
|--------|---------------------|
| Phase 1: direct request-response (v0.1.0) | ✅ Yes — gossipsub listener kept for backward compat |
| Phase 1.5: state snapshots (v0.1.0) | ✅ Yes — new DHT keys, old keys unchanged |
| `CONSENSUS_DIRECT_MODE` flag | ✅ Yes — disable to fall back to gossipsub mode |
| Future: Phase 2 (tx-type sharding) | Will be backward compatible via protocol negotiation |

---

## Additional Resources

- [CONSENSUS_DOCS.md](./CONSENSUS_DOCS.md) — Architecture, API reference, protocol details (for developers)
- [CONSENSUS_ROADMAP.md](./CONSENSUS_ROADMAP.md) — 4-phase scaling plan
- [CONSENSUS_DEPLOY.md](./CONSENSUS_DEPLOY.md) — Production deployment guide (Docker Compose, K8s, Terraform, CI/CD)
- [Main project README](../../README.md) — Feedo ecosystem overview