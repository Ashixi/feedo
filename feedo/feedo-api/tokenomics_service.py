import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import CreditBalance, CreditTransaction

logger = logging.getLogger("feedo_tokenomics")

class TokenomicsService:
    @staticmethod
    async def get_balances(db: AsyncSession, wallet_address: str) -> dict:
        stmt = select(CreditBalance).where(CreditBalance.wallet_address == wallet_address)
        result = await db.execute(stmt)
        balance_record = result.scalars().first()
        balance = balance_record.balance if balance_record else 0
        
        return {
            "tokens": balance,
            "reputation_score": 0,
            "queries_served": 0,
            "storage_uptime": 0
        }

    @staticmethod
    async def reward_peer(db: AsyncSession, wallet_address: str, amount: int, reason: str = "reward"):
        stmt = select(CreditBalance).where(CreditBalance.wallet_address == wallet_address)
        result = await db.execute(stmt)
        balance_record = result.scalars().first()
        
        if not balance_record:
            balance_record = CreditBalance(wallet_address=wallet_address, balance=amount)
            db.add(balance_record)
        else:
            balance_record.balance += amount
            
        await db.commit()
        logger.info(f"Rewarded peer {wallet_address} with {amount} tokens (reason: {reason}).")

    @staticmethod
    async def pay_for_query(db: AsyncSession, wallet_address: str, cost: int, allow_free_quota: bool = True) -> bool:
        stmt = select(CreditBalance).where(CreditBalance.wallet_address == wallet_address)
        result = await db.execute(stmt)
        balance_record = result.scalars().first()
        
        current_balance = balance_record.balance if balance_record else 0
        
        if current_balance >= cost:
            balance_record.balance -= cost
            await db.commit()
            logger.info(f"Charged {wallet_address} {cost} tokens for query.")
            return True
        else:
            if allow_free_quota:
                logger.warning(f"[BOOTSTRAPPING MODE] Peer {wallet_address} has {current_balance} tokens, but cost is {cost}. Allowing anyway for network bootstrap.")
                return True
            else:
                logger.warning(f"Payment rejected: {wallet_address} has insufficient funds.")
                return False

    @staticmethod
    async def claim_tokens(db: AsyncSession, wallet_address: str, amount: int, min_threshold: int = 5000) -> bool:
        stmt = select(CreditBalance).where(CreditBalance.wallet_address == wallet_address)
        result = await db.execute(stmt)
        balance_record = result.scalars().first()
        
        if not balance_record or balance_record.balance < amount:
            return False
            
        if amount < min_threshold:
            return False
            
        balance_record.balance -= amount
        await db.commit()
        logger.info(f"Peer {wallet_address} claimed {amount} tokens off-chain.")
        return True

    @staticmethod
    async def reward_query_hit(db: AsyncSession, author_pubkey: str, compute_node_pubkey: str, fee_amount: int):
        # Simplistic split: 50% to author, 50% to compute node
        author_cut = fee_amount // 2
        compute_cut = fee_amount - author_cut
        
        if author_pubkey:
            await TokenomicsService.reward_peer(db, author_pubkey, author_cut, reason="query_hit_author")
        if compute_node_pubkey:
            await TokenomicsService.reward_peer(db, compute_node_pubkey, compute_cut, reason="query_hit_compute")

    @staticmethod
    async def reward_unique_content(db: AsyncSession, wallet_address: str, reputation_amount: int):
        await TokenomicsService.reward_peer(db, wallet_address, reputation_amount, reason="unique_content")

    @staticmethod
    async def reward_download_hit(db: AsyncSession, node_pubkey: str, fee_amount: int):
        await TokenomicsService.reward_peer(db, node_pubkey, fee_amount, reason="download_hit")

    @staticmethod
    async def slash_storage_node(db: AsyncSession, wallet_address: str, penalty_amount: int):
        stmt = select(CreditBalance).where(CreditBalance.wallet_address == wallet_address)
        result = await db.execute(stmt)
        balance_record = result.scalars().first()
        
        if balance_record:
            balance_record.balance = max(0, balance_record.balance - penalty_amount)
            await db.commit()
            logger.info(f"Slashed {wallet_address} for {penalty_amount} tokens.")
