from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, List
import time
import asyncio
from eth_account.messages import encode_defunct
from eth_account import Account
from contextlib import asynccontextmanager

# --- Models ---
class NodeRegistration(BaseModel):
    type: str  # "search", "storage", "consensus"
    p2p_addr: str
    internal_http: str
    public_domain: Optional[str] = None

class NodeRecord(BaseModel):
    node_id: str
    type: str
    p2p_addr: str
    internal_http: str
    public_domain: Optional[str] = None
    last_seen: float

# --- State ---
# In-memory registry mapping node_id -> NodeRecord
registry: Dict[str, NodeRecord] = {}

# --- Background Tasks ---
async def cleanup_stale_nodes():
    """Removes nodes that haven't sent a heartbeat in the last 60 seconds."""
    while True:
        try:
            current_time = time.time()
            stale_nodes = [
                node_id for node_id, record in registry.items()
                if current_time - record.last_seen > 60.0
            ]
            for node_id in stale_nodes:
                print(f"Removing stale node: {node_id}")
                del registry[node_id]
        except Exception as e:
            print(f"Error in cleanup task: {e}")
        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    task = asyncio.create_task(cleanup_stale_nodes())
    yield
    # Shutdown
    task.cancel()

app = FastAPI(title="Feedo Router Node", lifespan=lifespan)

# --- Authentication Middleware ---
def verify_signature(request: Request) -> str:
    """
    Verifies the Feedo signature and returns the recovered node_id (address).
    Raises HTTPException on failure.
    """
    node_id = request.headers.get("X-Feedo-Node-ID")
    timestamp_str = request.headers.get("X-Feedo-Timestamp")
    signature = request.headers.get("X-Feedo-Signature")

    if not node_id or not timestamp_str or not signature:
        raise HTTPException(status_code=401, detail="Missing Authentication Headers")

    try:
        timestamp_ms = int(timestamp_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")

    current_time_ms = int(time.time() * 1000)
    if abs(current_time_ms - timestamp_ms) > 5 * 60 * 1000:
        raise HTTPException(status_code=401, detail="Timestamp expired")

    # Payload format matches search-node
    payload = f"FeedoAction:{request.method}:{request.url.path}:{timestamp_str}"
    
    try:
        message = encode_defunct(text=payload)
        recovered_address = Account.recover_message(message, signature=signature)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid signature: {str(e)}")

    if recovered_address.lower() != node_id.lower():
        raise HTTPException(status_code=401, detail="Signature does not match Node ID")

    return recovered_address.lower()

# --- Endpoints ---

@app.post("/register")
async def register_node(payload: NodeRegistration, request: Request):
    """Register a new node in the network."""
    node_id = verify_signature(request)
    
    record = NodeRecord(
        node_id=node_id,
        type=payload.type,
        p2p_addr=payload.p2p_addr,
        internal_http=payload.internal_http,
        public_domain=payload.public_domain,
        last_seen=time.time()
    )
    
    is_new = node_id not in registry
    registry[node_id] = record
    
    print(f"[{'NEW' if is_new else 'UPDATE'}] Node {node_id} ({payload.type}) registered. IP: {payload.internal_http}")
    return {"status": "success", "message": "Node registered"}

@app.post("/heartbeat")
async def node_heartbeat(request: Request):
    """Update the last_seen timestamp for a node."""
    node_id = verify_signature(request)
    
    if node_id not in registry:
        raise HTTPException(status_code=404, detail="Node not found. Please /register first.")
        
    registry[node_id].last_seen = time.time()
    return {"status": "success"}

@app.get("/discover")
async def discover_nodes(type: Optional[str] = None):
    """
    Returns active nodes.
    If 'type' is specified, returns only nodes of that type.
    """
    nodes = []
    for record in registry.values():
        if type and record.type != type:
            continue
        nodes.append(record.model_dump())
        
    return {"nodes": nodes}

@app.get("/explorer/stats")
async def stats():
    """Returns network statistics."""
    counts = {}
    for r in registry.values():
        counts[r.type] = counts.get(r.type, 0) + 1
        
    return {
        "status": "online",
        "total_nodes": len(registry),
        "by_type": counts
    }
