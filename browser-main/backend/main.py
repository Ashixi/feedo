import os
import re
from typing import Optional, List, Dict, Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Depends, status, Response

from backend.shemas import UserProfile, ConnectedDApp, PrivacySettings, BookmarkItem, SemanticQueryRequest, ContentPublishRequest

app = FastAPI(
    title="User Profile Management API",
    description="Mock API for user profile and connected dApps with session-key authorization.",
    version="0.1.0",
)

mock_profile = UserProfile(
    public_key="a1b2c3d4e5f60123456789abcdefabcdef1234567890abcdefabcdef12345678",
    privacy=PrivacySettings(
        block_trackers=True,
        require_tx_confirmation=True,
        share_analytics=False,
    ),
    dapps=[
        ConnectedDApp(
            dapp_id="dapp-1",
            name="Sample Swap",
            permissions=["read_address", "sign_tx"],
        )
    ],
)

FEEDO_NODE_BASE_URL = os.getenv("FEEDO_NODE_BASE_URL", "http://localhost:9000")


def extract_session_key(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_key: Optional[str] = Header(None, alias="X-User-Key"),
) -> str:
    session_key = None
    if x_user_key:
        session_key = x_user_key.strip()
    elif authorization:
        if authorization.lower().startswith("bearer "):
            session_key = authorization[7:].strip()
        else:
            session_key = authorization.strip()

    if not session_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mock authorization required: provide X-User-Key or Authorization header.",
        )

    if not re.fullmatch(r"[0-9a-fA-F]{32,}", session_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mock authorization key must be a hex session/public key.",
        )

    return session_key


def authorize_user(session_key: str = Depends(extract_session_key)) -> UserProfile:
    if session_key != mock_profile.public_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Mock session not recognized for the current profile.",
        )
    return mock_profile


def parse_crdt_bookmarks(state: Any) -> List[Dict[str, Any]]:
    if isinstance(state, list):
        return state

    if isinstance(state, dict):
        for candidate in ("value", "state", "items", "bookmarks", "entries", "data"):
            if candidate in state and isinstance(state[candidate], list):
                return state[candidate]

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Unexpected CRDT state format from Feedo node.",
    )


async def fetch_remote_bookmarks(object_id: str) -> List[Dict[str, Any]]:
    url = f"{FEEDO_NODE_BASE_URL}/crdt/{object_id}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)

    if response.status_code == 404:
        return []

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to read CRDT state from Feedo node: {response.status_code}",
        )

    try:
        payload = response.json()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid JSON returned from Feedo node.",
        )

    return parse_crdt_bookmarks(payload)


async def post_crdt_mutations(object_id: str, mutations: List[Dict[str, Any]]) -> None:
    url = f"{FEEDO_NODE_BASE_URL}/crdt/mutate"
    payload = {"object_id": object_id, "mutations": mutations}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)

    if response.status_code not in (200, 201):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to mutate CRDT state on Feedo node: {response.status_code}",
        )


@app.post("/semantic/query", response_model=Dict[str, Any])
async def proxy_semantic_query(
    query: SemanticQueryRequest,
    profile: UserProfile = Depends(authorize_user),
) -> Dict[str, Any]:
    url = f"{FEEDO_NODE_BASE_URL}/semantic/query"
    payload = query.dict(exclude_none=True)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload)

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Feedo semantic query failed: {response.status_code}",
        )

    try:
        return response.json()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid JSON returned from Feedo semantic query.",
        )


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@app.get("/profile", response_model=UserProfile)
def get_user_profile(profile: UserProfile = Depends(authorize_user)) -> UserProfile:
    return profile


@app.put("/profile", response_model=UserProfile)
def update_user_profile(
    updated_profile: UserProfile,
    profile: UserProfile = Depends(authorize_user),
) -> UserProfile:
    profile.public_key = updated_profile.public_key
    profile.privacy = updated_profile.privacy
    profile.dapps = updated_profile.dapps
    return profile


@app.patch("/profile/privacy", response_model=PrivacySettings)
def update_privacy_settings(
    privacy: PrivacySettings,
    profile: UserProfile = Depends(authorize_user),
) -> PrivacySettings:
    profile.privacy = privacy
    return profile.privacy


@app.get("/profile/dapps", response_model=List[ConnectedDApp])
def list_connected_dapps(profile: UserProfile = Depends(authorize_user)) -> List[ConnectedDApp]:
    return profile.dapps


@app.post("/profile/dapps", response_model=ConnectedDApp, status_code=status.HTTP_201_CREATED)
def add_connected_dapp(
    dapp: ConnectedDApp,
    profile: UserProfile = Depends(authorize_user),
) -> ConnectedDApp:
    existing = next((item for item in profile.dapps if item.dapp_id == dapp.dapp_id), None)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"dApp with id '{dapp.dapp_id}' is already connected.",
        )
    profile.dapps.append(dapp)
    return dapp


@app.delete("/profile/dapps/{dapp_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_connected_dapp(
    dapp_id: str,
    profile: UserProfile = Depends(authorize_user),
) -> None:
    profile.dapps = [item for item in profile.dapps if item.dapp_id != dapp_id]
    return None


def merge_bookmarks(local_bookmarks: List[Dict[str, Any]], remote_bookmarks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}

    for item in remote_bookmarks:
        bookmark_id = item.get("id")
        if bookmark_id:
            merged[bookmark_id] = item

    for item in local_bookmarks:
        bookmark_id = item.get("id")
        if not bookmark_id:
            continue
        if bookmark_id not in merged:
            merged[bookmark_id] = item

    return list(merged.values())


@app.post("/bookmarks/sync", response_model=List[BookmarkItem])
async def sync_bookmarks(
    bookmarks: List[BookmarkItem],
    profile: UserProfile = Depends(authorize_user),
) -> List[BookmarkItem]:
    object_id = f"bookmarks:{profile.public_key}"
    remote_bookmarks = await fetch_remote_bookmarks(object_id)
    local_bookmarks = [bookmark.dict(exclude_none=True) for bookmark in bookmarks]

    remote_ids = {bookmark["id"] for bookmark in remote_bookmarks if "id" in bookmark}
    mutations: List[Dict[str, Any]] = []

    for bookmark in local_bookmarks:
        if bookmark["id"] not in remote_ids:
            mutations.append(
                {
                    "type": "upsert",
                    "key": bookmark["id"],
                    "value": bookmark,
                }
            )

    if mutations:
        await post_crdt_mutations(object_id, mutations)

    merged_bookmarks = merge_bookmarks(local_bookmarks, remote_bookmarks)
    return [BookmarkItem(**bookmark) for bookmark in merged_bookmarks]


@app.post("/content/publish", response_model=Dict[str, Any])
async def publish_content(
    request: ContentPublishRequest,
    profile: UserProfile = Depends(authorize_user),
) -> Dict[str, Any]:
    url = f"{FEEDO_NODE_BASE_URL}/content/publish"
    payload = request.dict(exclude_none=True)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload)

    if response.status_code not in (200, 201):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to publish content to Feedo node: {response.status_code}",
        )

    try:
        return response.json()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid JSON returned from Feedo node publish.",
        )


@app.get("/content/{hash_id}")
async def get_content(
    hash_id: str,
    profile: UserProfile = Depends(authorize_user),
) -> Response:
    url = f"{FEEDO_NODE_BASE_URL}/content/{hash_id}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url)

    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Content not found on Feedo node."
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch content from Feedo node: {response.status_code}",
        )

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/json")
    )
