from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
import httpx
import time
import logging

router = APIRouter()
logger = logging.getLogger("feedo_api.crdt")

RUST_API_URL = "http://127.0.0.1:8041"

class CrdtMutateRequest(BaseModel):
    object_id: str
    operation: str
    key: str
    value: str
    author: str
    signature: str

class CrdtWebhookPayload(BaseModel):
    object_id: str
    entries: dict

@router.get("/{object_id}")
async def get_crdt_state(object_id: str):
    """
    Fetch the current merged state of a CRDT object from the Rust Node.
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{RUST_API_URL}/local/crdt_get/{object_id}")
            if resp.status_code == 200:
                data = resp.json()
                if data is None:
                    return {"object_id": object_id, "entries": {}}
                
                # Rust returns a JSON string in the 'data' if it's a double-encoded Option<String>.
                # Let's handle it gracefully:
                import json
                if isinstance(data, str):
                    try:
                        return json.loads(data)
                    except:
                        pass
                return data
            else:
                raise HTTPException(status_code=500, detail="Failed to fetch from Rust node")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/mutate")
async def mutate_crdt(req: CrdtMutateRequest):
    """
    Publish a CRDT operation.
    In a real scenario, Python API might construct the Protobuf and sign it.
    Since Protobuf generation is complex dynamically, we can ask the client to send the pre-built Protobuf
    or Python can compile the proto locally. 
    For MVP, we can assume this endpoint receives raw fields, builds the protobuf, and sends to Rust.
    """
    # Build protobuf via Python protobuf library
    # Since we might not have the generated _pb2 locally, we will use a workaround:
    # Actually, the user has feedo.proto. We need to compile it or rely on the frontend sending protobuf bytes.
    # To keep this API functional without regenerating Python protos right now, 
    # we can expose another endpoint or just implement the protobuf compilation.
    pass

@router.post("/webhook")
async def crdt_webhook(payload: dict):
    """
    Webhook called by Rust core when a CRDT object is successfully merged/updated.
    Python can use this to update LanceDB for semantic search or update WebSockets.
    """
    object_id = payload.get("object_id")
    logger.info(f"CRDT Webhook received for object: {object_id}")
    # In future: update Read-Model / LanceDB
    return {"status": "ok"}
