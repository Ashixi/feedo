from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
import random
import httpx
import logging

logger = logging.getLogger("feed_service")

class FeedService:
    @staticmethod
    async def generate_feed(
        db: AsyncSession,
        brain,
        limit: int,
        offset: int,
        source_type: str,
        language: str,
        user=None,
        expose_vector_api: bool = False,
        vector_api_addr: str = "",
        vector_api_key: str = ""
    ):
        from models import Post
        post_ids_to_fetch = set()
        fetched_ai_count = 0
        num_random = 0
        rand_res = []
        rel_hash_ids = []
        disc_hash_ids = []
        
        if user and user.user_vector and brain:
            res = brain.get_anti_bubble_feed(
                user.user_vector, 
                limit=limit + offset, 
                source_type=source_type, 
                user_languages=user.preferred_languages, 
                user_geo=None
            )
            
            rel_offset = int(offset * 0.7)
            disc_offset = offset - rel_offset
            
            rel_hash_ids = [hid for hid, score, *_ in res.get("relevant", [])][rel_offset:]
            disc_hash_ids = [hid for hid, score, *_ in res.get("discovery", [])][disc_offset:]
            
            local_hash_ids = set(rel_hash_ids + disc_hash_ids)
            if local_hash_ids:
                stmt_local = select(Post.id).where(Post.hash_id.in_(local_hash_ids))
                local_ids_res = (await db.execute(stmt_local)).scalars().all()
                post_ids_to_fetch.update(local_ids_res)
            
            fetched_ai_count = len(post_ids_to_fetch)
            
            num_random = max(1, int(limit * 0.03))
            rand_stmt = select(Post.id).where(Post.parent_post_id == None, Post.item_type == 'post')
            if source_type != "main" and source_type != "general":
                rand_stmt = rand_stmt.where(Post.source_type == source_type)
            if post_ids_to_fetch:
                rand_stmt = rand_stmt.where(~Post.id.in_(post_ids_to_fetch))
                
            rand_stmt = rand_stmt.order_by(desc(Post.published_at)).limit(500)
            rand_pool = (await db.execute(rand_stmt)).scalars().all()
            if rand_pool:
                rand_res = random.sample(rand_pool, min(num_random, len(rand_pool)))
                post_ids_to_fetch.update(rand_res)

        if fetched_ai_count == 0:
            stmt = select(Post.id).where(Post.item_type == 'post')
            s = (source_type or "").lower()
            if s == "feed" or s == "native":
                stmt = stmt.where(Post.parent_post_id == None, Post.source_type == "native")
            elif s == "main":
                stmt = stmt.where(Post.parent_post_id == None, Post.source_type.in_(["native", "rss", "p2p_relay", "nostr"]))
            else:
                stmt = stmt.where(Post.parent_post_id == None, Post.source_type == s)
                
            if language and language != "all":
                stmt = stmt.where(Post.language == language)
                
            stmt = stmt.order_by(desc(Post.published_at)).offset(offset).limit(limit)
            fallback_ids = (await db.execute(stmt)).scalars().all()
            post_ids_to_fetch.update(fallback_ids)

        if not post_ids_to_fetch:
            return [], rel_hash_ids, disc_hash_ids, rand_res

        stmt = select(Post).where(Post.id.in_(post_ids_to_fetch), Post.item_type == 'post').options(
            selectinload(Post.author),
            selectinload(Post.duplicates).selectinload(Post.author)
        )
        result = await db.execute(stmt)
        posts = result.scalars().all()
        
        # Scoring
        scored_posts = []
        for p in posts:
            base_score = 1.0
            dup_count = len(p.duplicates)
            popularity_boost = dup_count * 0.5
            pub_date = p.published_at or datetime.now(timezone.utc).replace(tzinfo=None)
            age_hours = (datetime.now(timezone.utc).replace(tzinfo=None) - pub_date).total_seconds() / 3600.0
            time_penalty = max(0, age_hours * 0.05)
            
            noise = random.uniform(-0.35, 0.35)
            final_score = (base_score + popularity_boost - time_penalty) * (1.0 + noise)
            scored_posts.append((final_score, p))
            
        scored_posts.sort(key=lambda x: x[0], reverse=True)
        return scored_posts, rel_hash_ids, disc_hash_ids, rand_res
