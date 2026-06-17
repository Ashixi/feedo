import asyncio
import httpx
import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Identity, NetworkNode, ConsensusLog

import os

# Node URL (can be customized via environment variable)
NODE_API_URL = os.getenv("NODE_API_URL", "http://feedo_node:8040/api/v1")

async def fetch_and_index():
    """
    Background worker that fetches data from Feedo API and indexes it.
    """
    db = SessionLocal()
    try:
        async with httpx.AsyncClient() as client:
            try:
                # Example: Fetch identities
                # This endpoint should match what the actual feedo-api provides.
                response = await client.get(f"{NODE_API_URL}/identity/", timeout=30.0)
                if response.status_code == 200:
                    data = response.json()
                    for item in data.get("identities", []):
                        # Upsert identity logic
                        item_did = item.get("did") or item.get("public_id") or item.get("wallet_address") or "unknown"
                        item_pk = item.get("public_key") or item.get("wallet_address") or "unknown"
                        existing = db.query(Identity).filter(Identity.did == item_did).first()
                        if not existing:
                            new_id = Identity(
                                did=item_did,
                                public_key=item_pk,
                                reputation=item.get("reputation", 0.0)
                            )
                            db.add(new_id)
                        else:
                            existing.reputation = item.get("reputation", 0.0)
                    
                # Fetch NetworkNodes
                try:
                    peers_res = await client.get(f"{NODE_API_URL}/node/peers", timeout=10.0)
                    if peers_res.status_code == 200:
                        peers_data = peers_res.json()
                        for peer in peers_data.get("peers", []):
                            peer_id = peer.get("peer_id")
                            if not peer_id:
                                continue
                            existing_node = db.query(NetworkNode).filter(NetworkNode.peer_id == peer_id).first()
                            if not existing_node:
                                new_node = NetworkNode(
                                    peer_id=peer_id,
                                    is_supernode=peer.get("is_supernode", False),
                                    status="active"
                                )
                                db.add(new_node)
                            else:
                                existing_node.status = "active"
                                existing_node.is_supernode = peer.get("is_supernode", False)
                                existing_node.last_seen = datetime.datetime.utcnow()
                except httpx.RequestError as e:
                    print(f"Indexer Error fetching peers: {repr(e)}")

                db.commit()
            except httpx.RequestError as e:
                print(f"Indexer Error fetching data from Node: {repr(e)}")
                db.rollback()
    finally:
        db.close()

async def run_indexer(interval_seconds: int = 15):
    """
    Runs the indexer in a loop.
    """
    print(f"Starting Explorer Indexer (interval: {interval_seconds}s)")
    while True:
        await fetch_and_index()
        await asyncio.sleep(interval_seconds)
