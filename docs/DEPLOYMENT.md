# Feedo Deployment Guide 🌍

This guide explains how to deploy the Feedo Protocol microservices to a production environment (e.g., an Ubuntu VPS).

## 1. Server Requirements
- **OS**: Ubuntu 22.04 LTS (recommended)
- **RAM**: Minimum 4GB (LanceDB and ML models require memory)
- **CPU**: 2+ Cores
- **Storage**: 20GB+ (For PostgreSQL metadata and LanceDB vectors)
- **Docker**: Docker and Docker Compose installed.

## 2. Network Configuration (Ports)

You only need to expose two ports to the public internet:

1. **`443 TCP` (HTTPS)**: Used by Nginx/Cloudflare to securely route traffic to the Backend API (which runs internally on `8040`).
2. **`4001 UDP`**: Used by the Rust P2P Node for Kademlia DHT communication with other Supernodes.

> **Note:** Do NOT expose PostgreSQL (`5432`) or the internal Rust HTTP port (`8050`) to the public.

## 3. Deployment Steps

### Step 1: Clone the Repository
```bash
git clone https://github.com/your-org/feedo.git
cd feedo
```

### Step 2: Configure Environment
Create the `.env` file in the root of the project. You can copy the provided `.env.example`.

**`.env.example` Configuration:**
```env
# --- Database (for Python API and P2P Node) ---
POSTGRES_USER=feedo_user
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_DB=feedo

# --- Security & Cryptography ---
INGEST_API_KEY=your_secure_ingest_key_here
NODE_WALLET_PRIVATE_KEY=your_private_key_here

# --- Network Configuration (P2P & Web3) ---
POLYGON_RPC_URL=https://polygon-rpc.com

# Enter the IP of the main node to connect to.
# If left empty, this node will become a "Genesis" node for a new network.
# Note: Docker Compose will automatically read this variable from the .env file and pass it to the feedo-p2p container.
# Example: /ip4/1.2.3.4/udp/4001/p2p/12D3KooWG...
BOOTSTRAP_NODES=

# --- Node Identity ---
NODE_WALLET_ADDRESS=your_wallet_address_here

# (REQUIRED) Address of the Main Treasury/Bank to report work for satoshis.
TREASURY_URL=https://api.feedo.network/api/v1/treasury/report

# --- Internal & Public URLs ---
PUBLIC_API_URL=https://api.feedo.network
INGEST_URL=http://feedo-backend:8040/api/v1/ingest/post
RUST_CORE_URL=http://feedo-p2p:8041
```

### Step 3: Configure Docker Compose Files

The project uses two separate Docker Compose files: one for the main node and one for the Nostr worker. You can copy these directly.

**1. Main Stack (`docker-compose.yml`)**
Create `docker-compose.yml` in the root:
```yaml
version: '3.8'

services:
  db:
    image: postgres:15-alpine
    restart: always
    env_file:
      - .env
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5

  feedo-backend:
    image: itsshas/feedo-backend:latest
    container_name: feedo-backend
    restart: always
    ports:
      - "8040:8040"
    env_file:
      - .env
    environment:
      - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
    depends_on:
      db:
        condition: service_healthy

  feedo-p2p:
    image: itsshas/feedo-p2p:latest
    container_name: feedo-p2p
    restart: always
    ports:
      - "4001:4001/udp"
    env_file:
      - .env
    environment:
      - DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      - PYTHON_API_URL=http://feedo-backend:8040
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
    depends_on:
      db:
        condition: service_healthy
      feedo-backend:
        condition: service_started
    volumes:
      - rust_db_data:/app/db

volumes:
  postgres_data:
  rust_db_data:
```

**2. Nostr Bridge Stack (`docker-compose.nostr.yml`)**
Create `docker-compose.nostr.yml` in the root:
```yaml
version: '3.8'
services:
  feedo-nostr-bridge:
    image: itsshas/feedo-nostr-bridge:latest
    container_name: feedo-nostr-bridge
    restart: always
    env_file:
      - .env
    environment:
      # Заміни localhost на IP-адресу або домен головної ноди, якщо Nostr працює на іншому сервері
      - INGEST_URL=${INGEST_URL:-http://localhost:8040/api/v1/ingest/post}
      - INGEST_API_KEY=${INGEST_API_KEY}
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
```

### Step 4: Run Docker Compose
To start the main stack:
```bash
docker-compose up -d
```
To start the Nostr bridge:
```bash
docker-compose -f docker-compose.nostr.yml up -d
```

### Step 4: Reverse Proxy (Nginx / Cloudflare)
To serve the API on a domain (e.g., `api.feedo.network`), configure a reverse proxy to forward traffic to `127.0.0.1:8040`.

**Example Nginx Config:**
```nginx
server {
    listen 80;
    server_name api.feedo.network;

    location / {
        proxy_pass http://127.0.0.1:8040;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Add SSL certificates using Certbot:
```bash
sudo certbot --nginx -d api.feedo.network
```

## 4. Updates & Maintenance
To pull new code and restart services:
```bash
git pull origin main
docker-compose build --no-cache
docker-compose up -d --force-recreate
```
