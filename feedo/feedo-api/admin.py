# feedo-api/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

from database import get_db
from models import User, Post
from auth import validate_zero_trust_request

router = APIRouter(prefix="/admin", tags=["Admin"])

async def verify_admin(wallet_address: str, timestamp: int, signature: str, db: AsyncSession):
    """Допоміжна функція для перевірки прав адміна"""
    validate_zero_trust_request(wallet_address, timestamp, {}, signature)
    stmt = select(User).where(User.wallet_address == wallet_address)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ заборонено. Ви не адміністратор.")
    return user

class AdminActionReq(BaseModel):
    admin_wallet: str
    target_id: str
    timestamp: int
    signature: str



import secrets
import hashlib
import logging
from typing import Optional

logger = logging.getLogger("feedo_api")

class CreateApiKeyReq(BaseModel):
    admin_wallet: str
    timestamp: int
    signature: str
    name: str
    role: str
    owner_address: Optional[str] = None
    expires_in_days: Optional[int] = None
    quotas: Optional[dict] = None

class RevokeApiKeyReq(BaseModel):
    admin_wallet: str
    timestamp: int
    signature: str
    key_id: int

class RotateApiKeyReq(BaseModel):
    admin_wallet: str
    timestamp: int
    signature: str
    key_id: int

@router.post("/api_keys/create")
async def create_api_key(req: CreateApiKeyReq, db: AsyncSession = Depends(get_db)):
    await verify_admin(req.admin_wallet, req.timestamp, req.signature, db)
    
    raw_key = secrets.token_urlsafe(32)
    hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
    
    expires_at = None
    if req.expires_in_days:
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=req.expires_in_days)
        
    from models import ApiKey, ApiKeyRole
    role_enum = ApiKeyRole(req.role)
    
    new_key = ApiKey(
        hashed_key=hashed_key,
        name=req.name,
        role=role_enum,
        owner_address=req.owner_address,
        expires_at=expires_at,
        rate_limit_bucket=req.quotas or {}
    )
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)
    
    return {
        "id": new_key.id,
        "name": new_key.name,
        "raw_key": raw_key,
        "message": "Store this raw key safely, it will not be shown again."
    }

@router.post("/api_keys/revoke")
async def revoke_api_key(req: RevokeApiKeyReq, db: AsyncSession = Depends(get_db)):
    await verify_admin(req.admin_wallet, req.timestamp, req.signature, db)
    from models import ApiKey
    
    stmt = select(ApiKey).where(ApiKey.id == req.key_id)
    key = (await db.execute(stmt)).scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
        
    key.revoked = True
    await db.commit()
    return {"message": "Key revoked successfully"}

@router.post("/api_keys/list")
async def list_api_keys(req: AdminActionReq, db: AsyncSession = Depends(get_db)):
    await verify_admin(req.admin_wallet, req.timestamp, req.signature, db)
    from models import ApiKey
    
    stmt = select(ApiKey)
    keys = (await db.execute(stmt)).scalars().all()
    
    return {
        "api_keys": [
            {
                "id": k.id,
                "name": k.name,
                "role": k.role.value,
                "owner": k.owner_address,
                "revoked": k.revoked,
                "created_at": k.created_at,
                "expires_at": k.expires_at
            } for k in keys
        ]
    }

@router.post("/api_keys/rotate")
async def rotate_api_key(req: RotateApiKeyReq, db: AsyncSession = Depends(get_db)):
    await verify_admin(req.admin_wallet, req.timestamp, req.signature, db)
    from models import ApiKey
    
    stmt = select(ApiKey).where(ApiKey.id == req.key_id)
    key = (await db.execute(stmt)).scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
        
    raw_key = secrets.token_urlsafe(32)
    hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
    
    key.hashed_key = hashed_key
    await db.commit()
    
    logger.info(f"AUDIT: API Key {key.id} ({key.name}) rotated by admin {req.admin_wallet}")
    
    return {
        "id": key.id,
        "name": key.name,
        "raw_key": raw_key,
        "message": "Key rotated successfully. Store this new raw key safely."
    }

@router.get("/p2p/reputation")
async def get_p2p_reputation(admin_wallet: str, timestamp: int, signature: str, db: AsyncSession = Depends(get_db)):
    await verify_admin(admin_wallet, timestamp, signature, db)
    
    try:
        from tokenomics_service import TokenomicsService
        # Return global reputation/balances or paginated version.
        # For now, let's just return a placeholder or query the top balances.
        # This will be fully implemented when Admin dashboard is built out.
        return {"message": "Reputation is now handled by TokenomicsService and PostgreSQL"}
    except Exception as e:
        logger.error(f"Failed to fetch p2p reputation: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch P2P reputation")