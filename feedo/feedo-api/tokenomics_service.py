import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import CreditBalance, CreditTransaction
import os
import httpx

logger = logging.getLogger("feedo_tokenomics")

# The developer's wallet to receive the 5% protocol tax
# Hardcoded to ensure the protocol creator receives their fee
DEVELOPER_WALLET = "npub1v2xsp3yq3h9t5d9sdkj2h8y3z444pnll8ffs5qmg5q60em03pc3qt96ny2"

TREASURY_URL = os.environ.get("TREASURY_URL", "").rstrip("/")
TREASURY_API_KEY = os.environ.get("TREASURY_API_KEY", "")

def get_treasury_headers():
    return {"x-treasury-key": TREASURY_API_KEY} if TREASURY_API_KEY else {}

class TokenomicsService:
    @staticmethod
    async def get_or_create_balance(db: AsyncSession, wallet_address: str) -> CreditBalance:
        stmt = select(CreditBalance).where(CreditBalance.wallet_address == wallet_address)
        result = await db.execute(stmt)
        balance_record = result.scalars().first()
        
        if not balance_record:
            balance_record = CreditBalance(wallet_address=wallet_address, balance=0, accumulated_fractions=0.0, free_search_queries=10)
            db.add(balance_record)
            await db.commit()
            
        return balance_record

    @staticmethod
    async def get_balances(db: AsyncSession, wallet_address: str) -> dict:
        balance_record = await TokenomicsService.get_or_create_balance(db, wallet_address)
        return {
            "tokens": balance_record.balance,
            "free_search_queries": balance_record.free_search_queries,
            "reputation_score": 0,
            "queries_served": 0,
            "storage_uptime": 0
        }

    @staticmethod
    async def reward_peer(db: AsyncSession, wallet_address: str, amount: int, fraction: float = 0.0, reason: str = "reward"):
        balance_record = await TokenomicsService.get_or_create_balance(db, wallet_address)
        
        balance_record.balance += amount
        balance_record.accumulated_fractions += fraction
        
        # If accumulated fractions exceed 1.0, convert to integer balance
        if balance_record.accumulated_fractions >= 1.0:
            whole_parts = int(balance_record.accumulated_fractions)
            balance_record.balance += whole_parts
            balance_record.accumulated_fractions -= whole_parts
            
        await db.commit()
        logger.info(f"Rewarded peer {wallet_address} with {amount} tokens, {fraction} fractions (reason: {reason}).")

    @staticmethod
    async def pay_for_query_local(db: AsyncSession, wallet_address: str, cost: int, allow_free_quota: bool = True) -> bool:
        balance_record = await TokenomicsService.get_or_create_balance(db, wallet_address)
        
        # 1. Check free queries first
        if allow_free_quota and balance_record.free_search_queries > 0:
            balance_record.free_search_queries -= 1
            await db.commit()
            logger.info(f"[LOCAL] User {wallet_address} used a free search query. Remaining: {balance_record.free_search_queries}")
            return True
        
        # 2. Check balance if no free queries
        if balance_record.balance >= cost:
            balance_record.balance -= cost
            await db.commit()
            logger.info(f"[LOCAL] Charged {wallet_address} {cost} tokens for query.")
            return True
            
        logger.warning(f"[LOCAL] Payment rejected: {wallet_address} has insufficient funds.")
        return False

    @staticmethod
    async def pay_for_query(db: AsyncSession, wallet_address: str, cost: int, allow_free_quota: bool = True) -> bool:
        """Facade that either calls the local DB or the Remote Treasury."""
        if TREASURY_URL:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{TREASURY_URL}/api/v1/treasury/pay_query",
                        json={"wallet_address": wallet_address, "cost": cost, "allow_free_quota": allow_free_quota},
                        headers=get_treasury_headers(),
                        timeout=5.0
                    )
                if resp.status_code == 200:
                    logger.info(f"[REMOTE] Successfully charged {wallet_address} via Treasury.")
                    return True
                else:
                    logger.warning(f"[REMOTE] Treasury rejected payment for {wallet_address}: {resp.text}")
                    return False
            except Exception as e:
                logger.error(f"[REMOTE] Failed to connect to Treasury: {e}")
                return False
        else:
            return await TokenomicsService.pay_for_query_local(db, wallet_address, cost, allow_free_quota)

    @staticmethod
    async def process_search_query_rewards(db: AsyncSession, client_pubkey: str, relay_pubkey: str, feedo_node_pubkey: str, is_free: bool):
        # We don't use this one actively right now, but keeping for Variant B compatibility
        if is_free:
            return
        if relay_pubkey:
            await TokenomicsService.reward_peer(db, relay_pubkey, amount=1, fraction=0.0, reason="search_relay_reward")
        if feedo_node_pubkey:
            await TokenomicsService.reward_peer(db, feedo_node_pubkey, amount=1, fraction=0.9, reason="search_node_reward")
        await TokenomicsService.reward_peer(db, DEVELOPER_WALLET, amount=0, fraction=0.1, reason="search_protocol_tax")

    @staticmethod
    async def process_direct_client_search_rewards_local(db: AsyncSession, client_pubkey: str, feedo_node_pubkey: str, is_free: bool):
        """
        Rewards for Variant A (Direct Nostr Client API) - LOCAL DB.
        """
        if is_free:
            return
            
        if feedo_node_pubkey:
            await TokenomicsService.reward_peer(db, feedo_node_pubkey, amount=1, fraction=0.9, reason="direct_search_node_reward")
            
        await TokenomicsService.reward_peer(db, DEVELOPER_WALLET, amount=0, fraction=0.1, reason="direct_search_protocol_tax")

    @staticmethod
    async def process_direct_client_search_rewards(db: AsyncSession, client_pubkey: str, feedo_node_pubkey: str, is_free: bool):
        """Facade that either calls the local DB or the Remote Treasury."""
        if TREASURY_URL:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{TREASURY_URL}/api/v1/treasury/process_rewards",
                        json={"client_pubkey": client_pubkey, "feedo_node_pubkey": feedo_node_pubkey, "is_free": is_free},
                        headers=get_treasury_headers(),
                        timeout=5.0
                    )
                if resp.status_code == 200:
                    logger.info(f"[REMOTE] Successfully processed rewards via Treasury.")
                else:
                    logger.warning(f"[REMOTE] Treasury failed to process rewards: {resp.text}")
            except Exception as e:
                logger.error(f"[REMOTE] Failed to connect to Treasury for rewards: {e}")
        else:
            await TokenomicsService.process_direct_client_search_rewards_local(db, client_pubkey, feedo_node_pubkey, is_free)

    @staticmethod
    async def claim_tokens(db: AsyncSession, wallet_address: str, amount: int, min_threshold: int = 5000) -> bool:
        balance_record = await TokenomicsService.get_or_create_balance(db, wallet_address)
        
        if balance_record.balance < amount or amount < min_threshold:
            return False
            
        balance_record.balance -= amount
        await db.commit()
        logger.info(f"Peer {wallet_address} claimed {amount} tokens off-chain.")
        return True

    @staticmethod
    async def reward_query_hit(db: AsyncSession, author_pubkey: str, compute_node_pubkey: str, fee_amount: int):
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
        balance_record = await TokenomicsService.get_or_create_balance(db, wallet_address)
        balance_record.balance = max(0, balance_record.balance - penalty_amount)
        await db.commit()
        logger.info(f"Slashed {wallet_address} for {penalty_amount} tokens.")
