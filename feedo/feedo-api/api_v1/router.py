from fastapi import APIRouter

from .identity import router as identity_router
from .content import router as content_router
from .semantic import router as semantic_router
from .graph import router as graph_router
from .node import router as node_router
from .crdt import router as crdt_router

api_v1_router = APIRouter()

api_v1_router.include_router(identity_router, prefix="/identity", tags=["Identity & Authorization"])
api_v1_router.include_router(content_router, prefix="/content", tags=["Content & Data"])
api_v1_router.include_router(semantic_router, prefix="/semantic", tags=["Semantic Graph & Search"])
api_v1_router.include_router(graph_router, prefix="/graph", tags=["Knowledge Topology"])
api_v1_router.include_router(node_router, prefix="/node", tags=["Node Administration"])
api_v1_router.include_router(crdt_router, prefix="/crdt", tags=["Dynamic CRDT State"])
