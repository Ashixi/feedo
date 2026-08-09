# Search Node — Deployment Guide

> **Audience**: Node operators deploying search-node in production.
> For architecture, see [SEARCH_DOCS.md](./SEARCH_DOCS.md).

---

## 1. Zero-Config Deployment

We have completely deprecated Docker Compose in favor of a native, bare-metal installation via `install.sh`. This ensures maximum performance, simplifies systemd integration, and removes container networking overhead.

### Installation Steps

Run the following command as root on your server:

```bash
curl -sSL https://raw.githubusercontent.com/Ashixi/feedo/main/install.sh | sudo bash
```
*(Or run `sudo bash install.sh` if you have the repository cloned locally).*

When prompted, select **3) Search Node (Python, ML)**.

### What the script does:
1. Installs all required system dependencies (Python, Git, etc.).
2. Clones the repository to `/opt/feedo-search`.
3. Sets up a Python virtual environment and installs `requirements.txt`.
4. Automatically discovers the network topology via `seed_nodes.json`.
5. Registers and starts the node as a `systemd` service (`feedo-search.service`).

## 2. Infrastructure Requirements

- **CPU**: 4+ vCPUs recommended
- **RAM**: 8 GB
- **Disk**: 40 GB+ SSD (NVMe preferred for LanceDB)
- **OS**: Ubuntu 22.04 or 24.04 LTS

## 3. Updating the Node

To pull the latest code and restart the node:

```bash
cd /opt/feedo-search && sudo git pull origin main && sudo systemctl restart feedo-search
```

View logs at any time:
```bash
sudo journalctl -u feedo-search -f
```