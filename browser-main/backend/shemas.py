from pydantic import BaseModel
from typing import Any, Dict, List, Optional

class PrivacySettings(BaseModel):
    block_trackers: bool = True
    require_tx_confirmation: bool = True
    share_analytics: bool = False

class ConnectedDApp(BaseModel):
    dapp_id: str
    name: str
    permissions: List[str] # наприклад: ["read_address", "sign_tx"]

class UserProfile(BaseModel):
    public_key: str # Ed25519 публічний ключ (hex)
    privacy: PrivacySettings = PrivacySettings()
    dapps: List[ConnectedDApp] = []

class BookmarkItem(BaseModel):
    id: str
    url: str
    title: Optional[str] = None
    created_at: Optional[str] = None
    tags: Optional[List[str]] = None

class SemanticQueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

class ContentPublishRequest(BaseModel):
    payload: Dict[str, Any]
    signature: str
    public_key: Optional[str] = None
