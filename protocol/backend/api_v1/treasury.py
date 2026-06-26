from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import os
import logging
from database import get_db

logger = logging.getLogger("feedo_treasury")
router = APIRouter()

TREASURY_API_KEY = os.environ.get("TREASURY_API_KEY", "")

def verify_api_key(x_treasury_key: str = Header(None)):
    if not TREASURY_API_KEY:
        # If treasury is not protected by key, allow, but warn (not recommended)
        return True
    if x_treasury_key != TREASURY_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Treasury API Key")
    return True

class PayQueryRequest(BaseModel):
    wallet_address: str
    cost: int
    allow_free_quota: bool = True

class RewardRequest(BaseModel):
    client_pubkey: str
    feedo_node_pubkey: str
    is_free: bool

@router.post("/pay_query")
async def pay_query(req: PayQueryRequest, db: AsyncSession = Depends(get_db), _: bool = Depends(verify_api_key)):
    """Deduct balance from user for a query (Called by Compute Nodes)."""
    from tokenomics_service import TokenomicsService
    success = await TokenomicsService.pay_for_query_local(db, req.wallet_address, req.cost, req.allow_free_quota)
    if not success:
        raise HTTPException(status_code=402, detail="Insufficient funds in Treasury.")
    return {"status": "SUCCESS"}

@router.post("/process_rewards")
async def process_rewards(req: RewardRequest, db: AsyncSession = Depends(get_db), _: bool = Depends(verify_api_key)):
    """Distribute rewards to Compute Node and Developer (Called by Compute Nodes)."""
    from tokenomics_service import TokenomicsService
    await TokenomicsService.process_direct_client_search_rewards_local(
        db, req.client_pubkey, req.feedo_node_pubkey, req.is_free
    )
    return {"status": "SUCCESS"}
