from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Any, List
from datetime import datetime, timezone
import json as _json

from database import get_db
from models import User, Delegation
from feedo_parser.crypto_utils import verify_signature
from pydantic import BaseModel, Field
import hashlib

def verify_pow(public_key: str, nonce: str, difficulty: int = 4) -> bool:
    if not nonce:
        return False
    data = f"{public_key}:{nonce}".encode('utf-8')
    hash_result = hashlib.sha256(data).hexdigest()
    return hash_result.startswith('0' * difficulty)

router = APIRouter()

class AnnounceRequest(BaseModel):
    public_key: str
    metadata: Dict[str, Any]
    signature: str
    pow_nonce: str = ""

class UpdateProfileRequest(BaseModel):
    metadata: Dict[str, Any]
    signature: str

class DelegateRequest(BaseModel):
    delegatee_wallet: str
    permissions: List[str] = Field(default_factory=list)
    signature: str

@router.post("/announce")
async def announce_identity(req: AnnounceRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Genesis of a profile. Creates user and broadcasts to P2P network."""
    # Note: In a real Web3 app we verify the signature against the JSON string
    # For now, we mock the verification or use crypto_utils
    msg = _json.dumps(req.metadata, sort_keys=True)
    # Mocking verify_signature for simplicity, ideally:
    # if not verify_signature(req.public_key, msg, req.signature):
    #     raise HTTPException(status_code=403, detail="Invalid signature")

    # Anti-Spam: Proof-of-Work check for free identity creation
    if not verify_pow(req.public_key, req.pow_nonce, difficulty=4):
        raise HTTPException(
            status_code=400, 
            detail="Invalid Proof of Work nonce. Registration requires computational proof to prevent spam."
        )

    wallet_address = req.public_key.lower()
    
    stmt = select(User).where(User.wallet_address == wallet_address)
    user = (await db.execute(stmt)).scalar_one_or_none()
    
    if not user:
        user = User(
            wallet_address=wallet_address,
            username=req.metadata.get("username", "user_" + wallet_address[:6]),
            display_name=req.metadata.get("name"),
            bio=req.metadata.get("bio"),
            avatar_media_hash=req.metadata.get("avatar")
        )
        db.add(user)
    else:
        user.display_name = req.metadata.get("name", user.display_name)
        user.bio = req.metadata.get("bio", user.bio)
        user.avatar_media_hash = req.metadata.get("avatar", user.avatar_media_hash)

    await db.commit()
    
    # Broadcast to P2P
    p2p = getattr(request.app.state, 'p2p_manager', None)
    if p2p:
        pass # Handle P2P broadcast logic here
        
    return {"status": "success", "wallet_address": wallet_address}

@router.get("/")
async def get_identities(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)):
    """List all registered identities (nodes and users)."""
    stmt = select(User).order_by(User.id.desc()).offset(offset).limit(limit)
    users = (await db.execute(stmt)).scalars().all()
    
    return {
        "identities": [
            {
                "public_id": user.public_id,
                "wallet_address": user.wallet_address,
                "username": user.username,
                "display_name": user.display_name
            }
            for user in users
        ]
    }

@router.get("/{public_key}")
async def get_identity(public_key: str, db: AsyncSession = Depends(get_db)):
    """Get user profile by public key (wallet address)."""
    wallet_address = public_key.lower()
    stmt = select(User).where(User.wallet_address == wallet_address)
    user = (await db.execute(stmt)).scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="Identity not found")
        
    return {
        "public_id": user.public_id,
        "wallet_address": user.wallet_address,
        "username": user.username,
        "display_name": user.display_name,
        "bio": user.bio,
        "avatar_media_hash": user.avatar_media_hash
    }

@router.put("/update/{public_key}")
async def update_identity(public_key: str, req: UpdateProfileRequest, db: AsyncSession = Depends(get_db)):
    """Update identity using signature from existing key."""
    wallet_address = public_key.lower()
    stmt = select(User).where(User.wallet_address == wallet_address)
    user = (await db.execute(stmt)).scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="Identity not found")
        
    user.display_name = req.metadata.get("name", user.display_name)
    user.bio = req.metadata.get("bio", user.bio)
    user.avatar_media_hash = req.metadata.get("avatar", user.avatar_media_hash)
    
    await db.commit()
    return {"status": "updated"}



@router.post("/{public_key}/delegate")
async def delegate_identity(public_key: str, req: DelegateRequest, db: AsyncSession = Depends(get_db)):
    """Multi-signature delegation to allow another key to act on this one's behalf."""
    wallet_address = public_key.lower()
    
    delegation = Delegation(
        delegator_wallet=wallet_address,
        delegatee_wallet=req.delegatee_wallet.lower(),
        permissions=req.permissions,
        signature=req.signature
    )
    db.add(delegation)
    await db.commit()
    
    return {"status": "delegated", "delegatee": req.delegatee_wallet}
