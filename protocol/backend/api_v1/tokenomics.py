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

class VerifyDepositRequest(BaseModel):
    tx_hash: str
    wallet_address: str

import os
import httpx

POLYGON_TREASURY_ADDRESS = os.getenv("POLYGON_TREASURY_ADDRESS", "0x0000000000000000000000000000000000000000").lower()
POLYGON_RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

# Store verified hashes to prevent double-spending in this simple implementation
# In production, this should be a DB table
verified_txs = set()

@router.post("/verify_deposit")
async def verify_deposit(req: VerifyDepositRequest, db: AsyncSession = Depends(get_db)):
    """Verifies a Polygon transaction and credits tokens to the user."""
    if req.tx_hash in verified_txs:
        raise HTTPException(status_code=400, detail="Transaction already verified")
        
    try:
        async with httpx.AsyncClient() as client:
            # 1. Get Transaction Details
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_getTransactionByHash",
                "params": [req.tx_hash],
                "id": 1
            }
            res = await client.post(POLYGON_RPC_URL, json=payload, timeout=10.0)
            tx_data = res.json().get("result")
            
            if not tx_data:
                raise HTTPException(status_code=404, detail="Transaction not found on Polygon")
                
            # 2. Verify receiver is our Treasury
            to_address = tx_data.get("to", "").lower()
            if to_address != POLYGON_TREASURY_ADDRESS:
                raise HTTPException(status_code=400, detail="Transaction was not sent to the Feedo Treasury")
                
            # 3. Check Receipt for Success Status
            receipt_payload = {
                "jsonrpc": "2.0",
                "method": "eth_getTransactionReceipt",
                "params": [req.tx_hash],
                "id": 2
            }
            rec_res = await client.post(POLYGON_RPC_URL, json=receipt_payload, timeout=10.0)
            receipt_data = rec_res.json().get("result")
            
            if not receipt_data or receipt_data.get("status") != "0x1":
                raise HTTPException(status_code=400, detail="Transaction failed or is pending")
                
            # 4. Calculate Tokens (e.g. 1 MATIC = 1000 Feedo Tokens)
            value_wei_hex = tx_data.get("value", "0x0")
            value_wei = int(value_wei_hex, 16)
            matic_amount = value_wei / (10 ** 18)
            
            if matic_amount <= 0:
                raise HTTPException(status_code=400, detail="Transaction value is zero")
                
            tokens_to_credit = int(matic_amount * 1000)
            
            # 5. Credit Account
            await TokenomicsService.reward_peer(db, req.wallet_address, tokens_to_credit, reason=f"polygon_deposit_{req.tx_hash}")
            verified_txs.add(req.tx_hash)
            
            balances = await TokenomicsService.get_balances(db, req.wallet_address)
            
            return {
                "status": "success",
                "message": f"Verified deposit of {matic_amount} MATIC. Credited {tokens_to_credit} tokens.",
                "balances": balances
            }
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RPC Error: {str(e)}")

