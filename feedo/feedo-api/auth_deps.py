import hashlib
import time
from collections import defaultdict
from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from models import ApiKeyRole
from database import AsyncSessionLocal

class RateLimiter:
    def __init__(self):
        # Maps identity (ip or wallet) to bucket: {"tokens": int, "last_refill": float}
        self.buckets = defaultdict(lambda: {"tokens": 0, "last_refill": 0.0})

    def check_limit(self, identity: str, capacity: int, refill_rate_per_sec: float) -> bool:
        now = time.time()
        bucket = self.buckets[identity]
        
        # Refill
        time_passed = now - bucket["last_refill"]
        new_tokens = time_passed * refill_rate_per_sec
        bucket["tokens"] = min(capacity, bucket["tokens"] + new_tokens)
        bucket["last_refill"] = now
        
        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True
        return False

rate_limiter = RateLimiter()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def get_api_key(request: Request, db: AsyncSession = Depends(get_db)):
    node_wallet = request.headers.get("x-node-wallet")
    node_sig = request.headers.get("x-node-signature")
    node_ts = request.headers.get("x-node-timestamp")
    
    if not (node_wallet and node_sig and node_ts):
        raise HTTPException(status_code=401, detail="Unauthorized: Node signature required. Decentralized network requires Ed25519 auth.")

    # Mutual Auth via Ed25519 Signature
    try:
        ts_int = int(node_ts)
        if abs(time.time() - ts_int) > 300: # 5 min window
            raise ValueError("Timestamp too old")
            
        from feedo_parser.crypto_utils import verify_signature
        data_to_sign = f"{node_wallet}:{ts_int}"
        digest_hex = hashlib.sha256(data_to_sign.encode('utf-8')).hexdigest()
        
        if not verify_signature(digest_hex, node_sig, node_wallet):
            raise ValueError("Invalid node signature")
            
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Node auth failed: {str(e)}")
        
    # We treat all valid signatures as having developer limits
    request.state.role = ApiKeyRole.DEVELOPER
    request.state.identity = f"node_{node_wallet}"
    request.state.k_limit = 1000
    
    allowed = rate_limiter.check_limit(request.state.identity, capacity=1000, refill_rate_per_sec=1000/60)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too Many Requests")
        
    return node_wallet
