from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Dict
from pydantic import BaseModel

router = APIRouter()

class DepositRequest(BaseModel):
    pubkey: str
    amount: int

class ClaimRequest(BaseModel):
    pubkey: str
    amount: int

@router.get("/{pubkey}")
async def get_tokenomics(pubkey: str, request: Request):
    """Get the full balance and reputation struct for a given user."""
    p2p_manager = getattr(request.app.state, 'p2p_manager', None)
    if not p2p_manager:
        raise HTTPException(status_code=503, detail="P2P Manager not initialized")
        
    balances = p2p_manager.reputation.get_balances(pubkey)
    return {"pubkey": pubkey, "balances": balances}

@router.post("/deposit")
async def deposit_tokens(req: DepositRequest, request: Request):
    """Mock endpoint to simulate purchasing tokens for testing AI Consumer flows."""
    p2p_manager = getattr(request.app.state, 'p2p_manager', None)
    if not p2p_manager:
        raise HTTPException(status_code=503, detail="P2P Manager not initialized")
        
    p2p_manager.reputation.reward_peer(req.pubkey, req.amount)
    
    return {
        "status": "success",
        "message": f"Deposited {req.amount} tokens to {req.pubkey}",
        "balances": p2p_manager.reputation.get_balances(req.pubkey)
    }

@router.post("/claim")
async def claim_tokens(req: ClaimRequest, request: Request):
    """Initiate withdrawal of off-chain tokens to smart contract."""
    p2p_manager = getattr(request.app.state, 'p2p_manager', None)
    if not p2p_manager:
        raise HTTPException(status_code=503, detail="P2P Manager not initialized")
        
    # Standard threshold is 5000, we can use a smaller one for testing if needed
    success = p2p_manager.reputation.claim_tokens(req.pubkey, req.amount, min_threshold=5000)
    
    if not success:
        raise HTTPException(status_code=400, detail="Insufficient funds or threshold not met for claim.")
        
    return {
        "status": "success",
        "message": f"Successfully claimed {req.amount} tokens. Proceed to Smart Contract with Proof.",
        "proof": "mock_cryptographic_proof_signature",
        "remaining_balances": p2p_manager.reputation.get_balances(req.pubkey)
    }
