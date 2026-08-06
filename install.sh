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
read -p "Select (1-3): " NODE_CHOICE < /dev/tty

case $NODE_CHOICE in
  1) NODE_TYPE="consensus" ;;
  2) NODE_TYPE="storage" ;;
  3) NODE_TYPE="search" ;;
  *) echo "Invalid choice."; exit 1;;
esac

echo "Starting installation for $NODE_TYPE node..."

# Variables
INSTALL_DIR="/opt/feedo"
REPO_URL="https://github.com/Ashixi/feedo.git"
REGISTRY_URL="https://raw.githubusercontent.com/Ashixi/feedo/main/seed_nodes.json"

# 1. Install System Dependencies
echo "[1/6] Installing system dependencies..."
apt-get update -yq
apt-get install -yq curl git build-essential python3 python3-pip python3-venv jq

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
  git pull origin main
else
  git clone $REPO_URL $INSTALL_DIR
  cd $INSTALL_DIR
fi

# 3. Generate Keys
echo "[3/6] Generating Node Identity (Keys & DID)..."
mkdir -p /etc/feedo
if [ ! -f "/etc/feedo/keys.json" ]; then
  # We use python to quickly generate an ed25519 key
  # pip install pynacl is needed
  python3 -m venv /opt/feedo/keygen-env
  /opt/feedo/keygen-env/bin/pip install --no-cache-dir pynacl eth_keys eth_utils "eth-hash[pycryptodome]"
  
  # Run our script if we have it, or a small inline script
  cat << 'EOF' > /tmp/feedo_keygen.py
import json
import secrets
from eth_keys import keys
from eth_utils import decode_hex

priv = keys.PrivateKey(secrets.token_bytes(32))
pub = priv.public_key
address = pub.to_checksum_address().lower()

data = {
    "private_key": priv.to_hex(),
    "public_key": pub.to_hex(),
    "address": address,
    "did": f"did:feedo:{address}"
}
with open("/etc/feedo/keys.json", "w") as f:
    json.dump(data, f, indent=4)
EOF
  /opt/feedo/keygen-env/bin/python /tmp/feedo_keygen.py
  echo "Keys generated successfully!"
else
  echo "Keys already exist at /etc/feedo/keys.json"
fi

NODE_DID=$(jq -r '.did' /etc/feedo/keys.json)
NODE_ADDR=$(jq -r '.address' /etc/feedo/keys.json)

# 4. Independent Registry (Zero Config Discovery)
echo "[4/6] Connecting to global registry..."
BOOTSTRAP_PEERS=""
if curl -s -f $REGISTRY_URL > /tmp/seed_nodes.json; then
  # Parse JSON if valid
  BOOTSTRAP_PEERS=$(jq -r '.peers | join(",")' /tmp/seed_nodes.json || echo "")
else
  echo "Warning: Could not fetch registry from $REGISTRY_URL. Node will start as a Genesis Node."
fi

# 5. Node Specific Setup
echo "[5/6] Configuring $NODE_TYPE..."
ENV_FILE="$INSTALL_DIR/microservices/$NODE_TYPE-node/.env"
mkdir -p "$INSTALL_DIR/microservices/$NODE_TYPE-node"

echo "NODE_DID=$NODE_DID" > $ENV_FILE
echo "NODE_ADDRESS=$NODE_ADDR" >> $ENV_FILE
echo "BOOTSTRAP_PEERS=$BOOTSTRAP_PEERS" >> $ENV_FILE

if [ "$NODE_TYPE" = "storage" ]; then
  read -p "Quota for Manifests (GB) [Default: 10]: " QUOTA_MAN < /dev/tty
  QUOTA_MAN=${QUOTA_MAN:-10}
  read -p "Quota for Files/Data (GB) [Default: 100]: " QUOTA_DATA < /dev/tty
  QUOTA_DATA=${QUOTA_DATA:-100}
  
  echo "STORAGE_PATH=/var/lib/feedo/storage" >> $ENV_FILE
  echo "QUOTA_MANIFESTS_GB=$QUOTA_MAN" >> $ENV_FILE
  echo "QUOTA_DATA_GB=$QUOTA_DATA" >> $ENV_FILE
  mkdir -p /var/lib/feedo/storage
  chmod 777 /var/lib/feedo/storage
  
  echo "Building Storage Node..."
  cd $INSTALL_DIR/microservices/storage-node
  source $HOME/.cargo/env
  cargo build --release
  EXEC_PATH="$INSTALL_DIR/microservices/storage-node/target/release/storage-node"

elif [ "$NODE_TYPE" = "consensus" ]; then
  echo "Building Consensus Node..."
  cd $INSTALL_DIR/microservices/consensus-node
  source $HOME/.cargo/env
  cargo build --release
  EXEC_PATH="$INSTALL_DIR/microservices/consensus-node/target/release/consensus-node"

elif [ "$NODE_TYPE" = "search" ]; then
  echo "Setting up Search Node (Python)..."
  cd $INSTALL_DIR/microservices/search-node
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  EXEC_PATH="$INSTALL_DIR/microservices/search-node/venv/bin/python $INSTALL_DIR/microservices/search-node/src/main.py"
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
