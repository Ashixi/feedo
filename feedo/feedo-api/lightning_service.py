import os
import logging
import httpx
from typing import Dict, Any

logger = logging.getLogger("feedo_lightning")

# LNBits configuration
LNBITS_URL = os.environ.get("LNBITS_URL", "https://demo.lnbits.com")
LNBITS_API_KEY = os.environ.get("LNBITS_API_KEY", "")

# Alby configuration
ALBY_TOKEN = os.environ.get("ALBY_BEARER_TOKEN", "")

class LightningService:
    @staticmethod
    async def create_invoice(amount: int, memo: str, webhook_url: str = None) -> Dict[str, Any]:
        """Create a Lightning invoice to receive funds (Deposit)."""
        if ALBY_TOKEN:
            return await LightningService._create_alby_invoice(amount, memo)
        elif LNBITS_API_KEY:
            return await LightningService._create_lnbits_invoice(amount, memo, webhook_url)
        else:
            # Simulated Mode
            logger.warning("No Lightning provider configured. Generating fake invoice.")
            import uuid
            fake_hash = str(uuid.uuid4())
            return {
                "payment_hash": fake_hash,
                "payment_request": f"lnbc_fake_invoice_{amount}_{fake_hash[:8]}"
            }

    @staticmethod
    async def _create_alby_invoice(amount: int, memo: str) -> Dict[str, Any]:
        url = "https://api.getalby.com/invoices"
        headers = {"Authorization": f"Bearer {ALBY_TOKEN}", "Content-Type": "application/json"}
        payload = {"amount": amount, "description": memo}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return {
                "payment_hash": data.get("payment_hash"),
                "payment_request": data.get("payment_request")
            }

    @staticmethod
    async def _create_lnbits_invoice(amount: int, memo: str, webhook_url: str = None) -> Dict[str, Any]:
        url = f"{LNBITS_URL}/api/v1/payments"
        headers = {"X-Api-Key": LNBITS_API_KEY, "Content-Type": "application/json"}
        payload = {"out": False, "amount": amount, "memo": memo}
        if webhook_url:
            payload["webhook"] = webhook_url
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return {
                "payment_hash": data.get("payment_hash"),
                "payment_request": data.get("payment_request")
            }

    @staticmethod
    async def check_invoice_status(payment_hash: str) -> bool:
        """Check if an invoice has been paid."""
        if ALBY_TOKEN:
            url = f"https://api.getalby.com/invoices/{payment_hash}"
            headers = {"Authorization": f"Bearer {ALBY_TOKEN}"}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return resp.json().get("settled", False)
            return False
            
        elif LNBITS_API_KEY:
            url = f"{LNBITS_URL}/api/v1/payments/{payment_hash}"
            headers = {"X-Api-Key": LNBITS_API_KEY}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return resp.json().get("paid", False)
            return False
            
        else:
            # In simulated mode, automatically "pay" the invoice for testing after a few seconds
            # In a real app we'd track time, but here we'll just return True so testing works.
            return True
        
    @staticmethod
    async def pay_invoice(invoice_string: str) -> bool:
        """Pay a Lightning invoice to send funds (Withdraw)."""
        if ALBY_TOKEN:
            url = "https://api.getalby.com/payments/bolt11"
            headers = {"Authorization": f"Bearer {ALBY_TOKEN}", "Content-Type": "application/json"}
            payload = {"invoice": invoice_string}
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers)
                return resp.status_code in (200, 201)
                
        elif LNBITS_API_KEY:
            url = f"{LNBITS_URL}/api/v1/payments"
            headers = {"X-Api-Key": LNBITS_API_KEY, "Content-Type": "application/json"}
            payload = {"out": True, "bolt11": invoice_string}
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers)
                return resp.status_code in (200, 201)
                
        else:
            logger.warning("Simulated payment success.")
            return True
