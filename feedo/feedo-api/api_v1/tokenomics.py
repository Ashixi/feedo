from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Dict
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from tokenomics_service import TokenomicsService

router = APIRouter()

class DepositRequest(BaseModel):
    pubkey: str
    amount: int

class ClaimRequest(BaseModel):
    pubkey: str
    amount: int

@router.get("/{pubkey}")
async def get_tokenomics(pubkey: str, db: AsyncSession = Depends(get_db)):
    """Get the full balance and reputation struct for a given user."""
    balances = await TokenomicsService.get_balances(db, pubkey)
    return {"pubkey": pubkey, "balances": balances}

@router.post("/deposit")
async def deposit_tokens(req: DepositRequest, db: AsyncSession = Depends(get_db)):
    """Mock endpoint to simulate purchasing tokens for testing AI Consumer flows."""
    await TokenomicsService.reward_peer(db, req.pubkey, req.amount, reason="deposit")
    balances = await TokenomicsService.get_balances(db, req.pubkey)
    return {
        "status": "success",
        "message": f"Deposited {req.amount} tokens to {req.pubkey}",
        "balances": balances
    }

@router.post("/claim")
async def claim_tokens(req: ClaimRequest, db: AsyncSession = Depends(get_db)):
    """Initiate withdrawal of off-chain tokens to smart contract."""
    # Standard threshold is 5000, we can use a smaller one for testing if needed
    success = await TokenomicsService.claim_tokens(db, req.pubkey, req.amount, min_threshold=5000)
    
    if not success:
        raise HTTPException(status_code=400, detail="Insufficient funds or threshold not met for claim.")
        
    balances = await TokenomicsService.get_balances(db, req.pubkey)
    return {
        "status": "success",
        "message": f"Successfully claimed {req.amount} tokens. Proceed to Smart Contract with Proof.",
        "proof": "mock_cryptographic_proof_signature",
        "remaining_balances": balances
    }
