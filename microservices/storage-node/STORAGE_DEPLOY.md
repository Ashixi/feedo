# Storage Node — Deployment Guide

> **Audience**: Node operators deploying storage-node in production.
> For architecture, see [STORAGE_DOCS.md](./STORAGE_DOCS.md).

---

## 1. Zero-Config Deployment

We have completely deprecated Docker Compose in favor of a native, bare-metal installation via `install.sh`. This ensures maximum performance, simplifies systemd integration, and removes container networking overhead.

### Installation Steps

Run the following command as root on your server:

```bash
curl -sSL https://raw.githubusercontent.com/Ashixi/feedo/main/install.sh | sudo bash
```
*(Or run `sudo bash install.sh` if you have the repository cloned locally).*

When prompted, select **2) Storage Node (Rust)**.

### What the script does:
1. Installs all required system dependencies (Rust, Git, Protobuf, etc.).
2. Clones the repository to `/opt/feedo-storage`.
3. Compiles the Rust binaries for production (`--release`).
4. Generates unique identity keys (`/etc/feedo/storage_keys.json`).
5. Automatically discovers the network topology via `seed_nodes.json`.
6. Registers and starts the node as a `systemd` service (`feedo-storage.service`).

## 2. Infrastructure Requirements

- **CPU**: 4+ vCPUs recommended
- **RAM**: 8 GB
- **Disk**: Dependent on your Quota Setting (e.g. 70 GB+)
- **OS**: Ubuntu 22.04 or 24.04 LTS

## 3. Updating the Node

To pull the latest code, recompile, and restart the node:

```bash
cd /opt/feedo-storage && sudo git pull origin main && source ~/.cargo/env && cd microservices && cargo build --release -p storage-node && sudo systemctl restart feedo-storage
```

*(Alternatively, you can just re-run `sudo bash install.sh` and select option 2).*

View logs at any time:
```bash
sudo journalctl -u feedo-storage -f
```