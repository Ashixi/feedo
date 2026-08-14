#!/bin/bash

set -e

echo "=========================================="
echo "🚀 Feedo Node Installer (Zero Config)"
echo "=========================================="

# Ensure root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (use sudo)"
  exit 1
fi

# Prompt for node type
echo "Which Feedo node would you like to install?"
echo "1) Consensus Node (Rust)"
echo "2) Storage Node (Rust)"
echo "3) Search Node (Python, ML)"
echo "4) All nodes (consensus + storage + search)"
read -p "Select (1-4): " NODE_CHOICE < /dev/tty

case $NODE_CHOICE in
  1) NODE_TYPES=(consensus) ;;
  2) NODE_TYPES=(storage) ;;
  3) NODE_TYPES=(search) ;;
  4) NODE_TYPES=(consensus storage search) ;;
  *) echo "Invalid choice."; exit 1;;
esac

install_node() {
  local NODE_TYPE="$1"

echo "Starting installation for $NODE_TYPE node..."

# Variables
INSTALL_DIR="/opt/feedo-$NODE_TYPE"
REPO_URL="https://github.com/Ashixi/feedo.git"
REGISTRY_URL="https://raw.githubusercontent.com/Ashixi/feedo/main/seed_nodes.json"

# 1. Install System Dependencies
echo "[1/6] Installing system dependencies..."
apt-get update -yq
apt-get install -yq curl git build-essential python3 python3-pip python3-venv jq pkg-config libssl-dev protobuf-compiler

if [ "$NODE_TYPE" = "consensus" ] || [ "$NODE_TYPE" = "storage" ]; then
  if ! command -v cargo &> /dev/null; then
    echo "Installing Rust..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source $HOME/.cargo/env
  fi
fi

# 2. Clone Repository
echo "[2/6] Fetching latest Feedo source..."
if [ -d "$INSTALL_DIR" ]; then
  echo "Directory exists, pulling latest changes..."
  cd $INSTALL_DIR
  git fetch origin main
  git reset --hard origin/main
else
  git clone $REPO_URL $INSTALL_DIR
  cd $INSTALL_DIR
fi

# 3. Generate Keys (via Rust keygen binary)
echo "[3/6] Generating Node Identity (Keys & DID)..."
mkdir -p /etc/feedo
KEYS_FILE="/etc/feedo/${NODE_TYPE}_keys.json"
if [ ! -f "$KEYS_FILE" ]; then
  echo "Compiling feedo-keygen..."
  source $HOME/.cargo/env
  cd $INSTALL_DIR/microservices
  cargo build --release -p feedo-keygen
  KEYGEN_BIN="$INSTALL_DIR/microservices/target/release/feedo-keygen"
  $KEYGEN_BIN > "$KEYS_FILE"
  echo "Keys generated successfully!"
else
  echo "Keys already exist at $KEYS_FILE"
fi

NODE_DID=$(jq -r '.did' "$KEYS_FILE")
NODE_ADDR=$(jq -r '.address' "$KEYS_FILE")
NODE_PRIV_KEY=$(jq -r '.private_key' "$KEYS_FILE")

# 4. Independent Registry (Zero Config Discovery)
echo "[4/6] Connecting to global registry..."
BOOTSTRAP_PEERS=""
CONSENSUS_NODE_URL=""
STORAGE_NODE_URL=""
SEARCH_NODE_URL=""
SEARCH_PEERS=""

if curl -s -f $REGISTRY_URL > /tmp/seed_nodes.json 2>/dev/null; then
  # Extract P2P addresses for bootstrap
  BOOTSTRAP_PEERS=$(jq -r '[.nodes[].p2p_addr] | join(",")' /tmp/seed_nodes.json 2>/dev/null || echo "")

  # Extract HTTP URLs by node type — fully automatic service discovery
  CONSENSUS_NODE_URL=$(jq -r '[.nodes[] | select(.type=="consensus") | .http_url] | first' /tmp/seed_nodes.json 2>/dev/null || echo "")
  STORAGE_NODE_URL=$(jq -r '[.nodes[] | select(.type=="storage") | .http_url] | first' /tmp/seed_nodes.json 2>/dev/null || echo "")
  SEARCH_NODE_URL=$(jq -r '[.nodes[] | select(.type=="search") | .http_url] | first' /tmp/seed_nodes.json 2>/dev/null || echo "")
  # All search node HTTP URLs (for P2P peer discovery — search nodes use HTTP, not libp2p)
  SEARCH_PEERS=$(jq -r '[.nodes[] | select(.type=="search") | .http_url] | join(",")' /tmp/seed_nodes.json 2>/dev/null || echo "")

  echo "  Consensus: ${CONSENSUS_NODE_URL:-not found in registry}"
  echo "  Storage:   ${STORAGE_NODE_URL:-not found in registry}"
  echo "  Search:    ${SEARCH_NODE_URL:-not found in registry}"
else
  echo "Warning: Could not fetch registry from $REGISTRY_URL. Node will start as a Genesis Node."
fi

# 5. Node Specific Setup
echo "[5/6] Configuring $NODE_TYPE..."
ENV_FILE="$INSTALL_DIR/microservices/$NODE_TYPE-node/.env"
mkdir -p "$INSTALL_DIR/microservices/$NODE_TYPE-node"

echo "NODE_DID=$NODE_DID" > $ENV_FILE
echo "NODE_ADDRESS=$NODE_ADDR" >> $ENV_FILE
echo "NODE_WALLET_ADDRESS=$NODE_ADDR" >> $ENV_FILE
echo "NODE_PRIVATE_KEY=$NODE_PRIV_KEY" >> $ENV_FILE
echo "BOOTSTRAP_NODES=$BOOTSTRAP_PEERS" >> $ENV_FILE
echo "CONSENSUS_NODE_URL=$CONSENSUS_NODE_URL" >> $ENV_FILE
echo "STORAGE_NODE_URL=$STORAGE_NODE_URL" >> $ENV_FILE
echo "SEARCH_NODE_URL=$SEARCH_NODE_URL" >> $ENV_FILE
echo "ETH_RPC_URL=https://polygon.llamarpc.com" >> $ENV_FILE

if [ "$NODE_TYPE" = "storage" ]; then
  read -p "Total Storage Quota (GB) [Default: 70]: " QUOTA_TOTAL < /dev/tty
  QUOTA_TOTAL=${QUOTA_TOTAL:-70}

  echo "STORAGE_PATH=/var/lib/feedo/storage" >> $ENV_FILE
  echo "QUOTA_TOTAL_GB=$QUOTA_TOTAL" >> $ENV_FILE
  mkdir -p /var/lib/feedo/storage
  chmod 777 /var/lib/feedo/storage
  
  echo "Building Storage Node..."
  cd $INSTALL_DIR/microservices
  source $HOME/.cargo/env
  cargo build --release -p storage-node
  EXEC_PATH="$INSTALL_DIR/microservices/target/release/storage-node"

elif [ "$NODE_TYPE" = "consensus" ]; then
  echo "Building Consensus Node..."
  cd $INSTALL_DIR/microservices
  source $HOME/.cargo/env
  cargo build --release -p consensus-node
  EXEC_PATH="$INSTALL_DIR/microservices/target/release/consensus-node"

elif [ "$NODE_TYPE" = "search" ]; then
  echo "Setting up Search Node (Python)..."
  cd $INSTALL_DIR/microservices/search-node
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt

  # P2P: search nodes discover each other via HTTP URLs (KNOWN_PEERS),
  # not libp2p multiaddrs (BOOTSTRAP_NODES is for consensus/storage only).
  echo "KNOWN_PEERS=$SEARCH_PEERS" >> $ENV_FILE
  read -p "Public URL of THIS search node (e.g. http://YOUR_IP:8000): " PUBLIC_API_URL < /dev/tty
  echo "PUBLIC_API_URL=${PUBLIC_API_URL:-http://127.0.0.1:8000}" >> $ENV_FILE

  EXEC_PATH="$INSTALL_DIR/microservices/search-node/venv/bin/python $INSTALL_DIR/microservices/search-node/main.py"
fi

# 6. Systemd Registration
echo "[6/6] Registering Systemd Service..."
SERVICE_FILE="/etc/systemd/system/feedo-$NODE_TYPE.service"
cat << EOF > $SERVICE_FILE
[Unit]
Description=Feedo $NODE_TYPE Node
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/microservices/$NODE_TYPE-node
ExecStart=$EXEC_PATH
Restart=on-failure
RestartSec=5
EnvironmentFile=$ENV_FILE

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable feedo-$NODE_TYPE
systemctl start feedo-$NODE_TYPE

echo "=========================================="
echo "✅ Installation Complete!"
echo "Your Node DID is: $NODE_DID"
echo "Node is running in the background via systemd."
echo "View logs: journalctl -u feedo-$NODE_TYPE -f"
if [ -z "$BOOTSTRAP_PEERS" ]; then
  echo ""
  echo "⚠️ IMPORTANT: You are running as a Genesis Node."
  echo "Please add your Node IP and Peer ID to the seed_nodes.json in the repository so others can connect to you."
fi
echo "=========================================="
}

for NODE_TYPE in "${NODE_TYPES[@]}"; do
  install_node "$NODE_TYPE"
done
