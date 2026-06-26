from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
import os
import logging
from pydantic import BaseModel
from sqlalchemy import select
from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/{address}/balance")
async def get_wallet_balance(address: str, request: Request):
    """
    Get the virtual off-chain balance of an address or Feedo ID.
    Proxies the request to the local Rust node's accounting module.
    """
    # RUST_CORE_URL is typically "http://127.0.0.1:8041/local/publish"
    rust_url_base = os.getenv("RUST_CORE_URL", "http://127.0.0.1:8041/local/publish").replace("/local/publish", "")
    
    try:
        rust_balance_url = f"{rust_url_base}/local/balance/{address}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(rust_balance_url, timeout=5.0)
            
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.warning(f"Failed to fetch balance from Rust for {address}: {resp.text}")
            return {"balance": 0.0, "status": "fallback"}
            
    except Exception as e:
        logger.error(f"Error proxying balance request for {address}: {e}")
        return {"balance": 0.0, "status": "error"}

class DepositRequest(BaseModel):
    wallet_address: str
    amount: int

class WithdrawRequest(BaseModel):
    wallet_address: str
    invoice_string: str
    amount: int
    event: dict  # The Nostr event authorizing the withdrawal

@router.post("/deposit/request")
async def request_deposit(req: DepositRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Generate a Lightning Invoice for the user to pay."""
    from lightning_service import LightningService
    from models import LightningInvoice
    if req.amount < 100:
        raise HTTPException(status_code=400, detail="Minimum deposit is 100 satoshis.")
        
    base_url = str(request.base_url).rstrip("/")
    webhook_url = f"{base_url}/api/v1/wallet/webhook"
    
    invoice_data = await LightningService.create_invoice(
        amount=req.amount,
        memo=f"Feedo Top Up: {req.wallet_address[:8]}...",
        webhook_url=webhook_url
    )
    
    new_invoice = LightningInvoice(
        payment_hash=invoice_data["payment_hash"],
        wallet_address=req.wallet_address,
        amount=req.amount,
        status="PENDING",
        invoice_string=invoice_data["payment_request"]
    )
    db.add(new_invoice)
    await db.commit()
    
    return {
        "payment_hash": invoice_data["payment_hash"],
        "payment_request": invoice_data["payment_request"],
        "amount": req.amount
    }

@router.get("/deposit/status/{payment_hash}")
async def check_deposit_status(payment_hash: str, db: AsyncSession = Depends(get_db)):
    """Frontend polls this to check if the user has paid the invoice."""
    from models import LightningInvoice
    from lightning_service import LightningService
    from tokenomics_service import TokenomicsService
    stmt = select(LightningInvoice).where(LightningInvoice.payment_hash == payment_hash)
    result = await db.execute(stmt)
    invoice = result.scalars().first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")
        
    if invoice.status == "PAID":
        return {"status": "PAID"}
        
    is_paid = await LightningService.check_invoice_status(payment_hash)
    if is_paid:
        invoice.status = "PAID"
        balance_record = await TokenomicsService.get_or_create_balance(db, invoice.wallet_address)
        balance_record.balance += invoice.amount
        await db.commit()
        logger.info(f"Invoice {payment_hash} paid via polling. Credited {invoice.amount} to {invoice.wallet_address}.")
        return {"status": "PAID"}
        
    return {"status": "PENDING"}

@router.post("/webhook")
async def webhook_handler(request: Request, db: AsyncSession = Depends(get_db)):
    """Handles webhooks from both LNBits and Alby when an invoice is paid."""
    from models import LightningInvoice
    from lightning_service import LightningService
    from tokenomics_service import TokenomicsService
    try:
        data = await request.json()
        
        # Extract payment hash (works for LNBits, and common Alby payload structures)
        payment_hash = data.get("payment_hash")
        if not payment_hash:
            payment_hash = data.get("invoice", {}).get("payment_hash")
        if not payment_hash:
            payment_hash = data.get("data", {}).get("payment_hash")
            
        if not payment_hash:
            return {"status": "ignored"}
            
        stmt = select(LightningInvoice).where(LightningInvoice.payment_hash == payment_hash)
        result = await db.execute(stmt)
        invoice = result.scalars().first()
        
        if not invoice or invoice.status == "PAID":
            return {"status": "ok"}
            
        # Verify with Alby/LNBits to prevent spoofing
        is_paid = await LightningService.check_invoice_status(payment_hash)
        if is_paid:
            invoice.status = "PAID"
            balance_record = await TokenomicsService.get_or_create_balance(db, invoice.wallet_address)
            balance_record.balance += invoice.amount
            await db.commit()
            logger.info(f"Webhook: Invoice {payment_hash} paid. Credited {invoice.amount} to {invoice.wallet_address}.")
            
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

@router.post("/withdraw")
async def withdraw_funds(req: WithdrawRequest, db: AsyncSession = Depends(get_db)):
    """Node operators / Relay owners withdraw their internal balance to a real Lightning wallet."""
    import json
    import hashlib
    import time
    from core.utils.crypto_utils import verify_signature
    from lightning_service import LightningService
    from tokenomics_service import TokenomicsService
    
    # 1. Verify the Nostr Event
    event = req.event
    if not event or "pubkey" not in event or "sig" not in event:
        raise HTTPException(status_code=401, detail="Missing or invalid authorization event.")
        
    if event["pubkey"] != req.wallet_address:
        raise HTTPException(status_code=401, detail="Pubkey mismatch in authorization event.")
        
    # Rebuild event ID to prevent spoofing
    serialized = json.dumps([
        0,
        event.get("pubkey"),
        event.get("created_at"),
        event.get("kind"),
        event.get("tags", []),
        event.get("content", "")
    ], separators=(',', ':'), ensure_ascii=False)
    
    expected_id = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    if expected_id != event.get("id"):
        raise HTTPException(status_code=401, detail="Event ID spoofing detected.")
        
    # Check signature
    if not verify_signature(expected_id, event.get("sig"), event.get("pubkey")):
        raise HTTPException(status_code=401, detail="Invalid Nostr signature.")
        
    # Prevent replay attacks: Check if invoice string is in the content and event is recent (within 5 minutes)
    if req.invoice_string not in event.get("content", ""):
        raise HTTPException(status_code=401, detail="Invoice not found in signed content.")
        
    now = int(time.time())
    if abs(now - event.get("created_at", 0)) > 300:
        raise HTTPException(status_code=401, detail="Authorization event expired (Replay protection).")

    # 2. Process withdrawal
    if req.amount < 1000:
        raise HTTPException(status_code=400, detail="Minimum withdrawal is 1000 satoshis.")
        
    balance_record = await TokenomicsService.get_or_create_balance(db, req.wallet_address)
    
    if balance_record.balance < req.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds in internal balance.")
        
    balance_record.balance -= req.amount
    await db.commit()
    
    success = await LightningService.pay_invoice(req.invoice_string)
    if success:
        logger.info(f"Withdrawal of {req.amount} for {req.wallet_address} successful.")
        return {"status": "SUCCESS", "message": "Invoice paid."}
    else:
        balance_record.balance += req.amount
        await db.commit()
        logger.error(f"Withdrawal failed. Refunded {req.amount} to {req.wallet_address}.")
        raise HTTPException(status_code=500, detail="Failed to pay lightning invoice. Funds refunded.")

@router.get("/topup", response_class=HTMLResponse)
async def get_topup_page():
    """Serves the Web UI for Lightning Top Up."""
    try:
        template_path = os.path.join(os.path.dirname(__file__), "..", "templates", "wallet.html")
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error serving wallet.html: {e}")
        return HTMLResponse(content="<h1>Error loading UI</h1>", status_code=500)
