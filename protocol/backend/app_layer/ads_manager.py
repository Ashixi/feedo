import logging
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import Post

logger = logging.getLogger(__name__)

class AdsManager:
    @staticmethod
    async def charge_ad_impression(db: AsyncSession, post_id: int, node_wallet: str, cost: int = 5) -> bool:
        """
        Charges the ad budget of a promoted post and rewards the node and developer.
        """
        from tokenomics_service import TokenomicsService, DEVELOPER_WALLET
        
        stmt = select(Post).where(Post.id == post_id)
        result = await db.execute(stmt)
        post = result.scalars().first()
        
        if not post or post.ad_budget < cost or not post.is_promoted:
            return False
            
        post.ad_budget -= cost
        if post.ad_budget < cost:
            post.is_promoted = False
            
        node_fraction = cost * 0.95
        dev_fraction = cost * 0.05
        
        await TokenomicsService.reward_peer(db, node_wallet, amount=0, fraction=node_fraction, reason="ad_impression_node")
        await TokenomicsService.reward_peer(db, DEVELOPER_WALLET, amount=0, fraction=dev_fraction, reason="ad_impression_dev")
        
        await db.commit()
        logger.info(f"Charged {cost} sats for ad impression on post {post_id}.")
        return True
