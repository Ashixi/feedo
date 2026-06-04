import asyncio
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, Base, get_db
from models import Identity, NetworkNode, ConsensusLog
from indexer import run_indexer

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Feedo Explorer Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    # Run the indexer task in the background
    asyncio.create_task(run_indexer(interval_seconds=15))

@app.get("/api/v1/network/summary")
def get_network_summary(db: Session = Depends(get_db)):
    nodes_count = db.query(NetworkNode).count()
    supernodes_count = db.query(NetworkNode).filter(NetworkNode.is_supernode == True).count()
    return {
        "total_nodes": nodes_count,
        "supernodes": supernodes_count,
        "network_status": "Healthy" if nodes_count > 0 else "Bootstrapping"
    }

@app.get("/api/v1/network/nodes")
def get_network_nodes(db: Session = Depends(get_db)):
    nodes = db.query(NetworkNode).all()
    return {"nodes": [{"id": n.id, "peer_id": n.peer_id, "is_supernode": n.is_supernode, "status": n.status, "last_seen": n.last_seen} for n in nodes]}

@app.get("/api/v1/identities")
def get_identities(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    identities = db.query(Identity).order_by(Identity.reputation.desc()).offset(skip).limit(limit).all()
    return {"identities": identities}

@app.get("/api/v1/consensus/history")
def get_consensus_history(limit: int = 20, db: Session = Depends(get_db)):
    logs = db.query(ConsensusLog).order_by(ConsensusLog.timestamp.desc()).limit(limit).all()
    return {"blocks": logs}

@app.get("/")
def read_root():
    return {"status": "Feedo Explorer Backend is running"}
