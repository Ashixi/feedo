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
        text: str = None,
        user=None,
        expose_vector_api: bool = False,
        vector_api_addr: str = "",
        vector_api_key: str = ""
    ):
        from models import Post
        from sqlalchemy.orm import selectinload
        import asyncio
        import httpx
        
        async def fetch_p2p(item_type: str, query_text: str, lim: int):
            try:
                async with httpx.AsyncClient() as client:
                    res = await client.post("http://127.0.0.1:8041/local/semantic_search", json={
                        "text_query": query_text,
                        "limit": lim,
                        "source_types": ["native", "rss", "p2p_relay", "nostr"],
                        "item_type": item_type
                    }, timeout=10.0)
                    if res.status_code == 200:
                        data = res.json()
                        return data.get("results", [])
            except Exception as e:
                logger.error(f"P2P search error: {e}")
            return []

        # If user has preferred_tags, trigger 70/30 anti-bubble logic via Federated P2P Search
        scored_posts_p2p = []
        if user and user.preferred_tags and offset == 0:
            limit_70 = max(1, int(limit * 0.7))
            limit_30 = limit - limit_70
            
            tags_query = " ".join(user.preferred_tags)
            
            # Fire both queries concurrently to Kademlia/Gossip network (will take ~3s)
            results_70, results_30 = await asyncio.gather(
                fetch_p2p("feed", tags_query, limit_70),
                fetch_p2p("feed_trending", "", limit_30)
            )
            
            # Merge results
            all_p2p_results = results_70 + results_30
            hash_ids_to_fetch = []
            seen = set()
            for r in all_p2p_results:
                hid = r.get("hash_id")
                if hid and hid not in seen:
                    seen.add(hid)
                    hash_ids_to_fetch.append(hid)
                    
            if hash_ids_to_fetch:
                fetch_stmt = select(Post).where(Post.hash_id.in_(hash_ids_to_fetch), Post.item_type == 'post').options(
                    selectinload(Post.author),
                    selectinload(Post.duplicates).selectinload(Post.author)
                )
                result = await db.execute(fetch_stmt)
                posts = result.scalars().all()
                
                post_map = {p.hash_id: p for p in posts}
                # Maintain order from the P2P result
                scored_posts_p2p = [ (1.0, post_map[hid]) for hid in hash_ids_to_fetch if hid in post_map ]

        if scored_posts_p2p:
            return scored_posts_p2p, [], [], []

        # Fallback to standard local chronological logic
        stmt = select(Post.id).where(Post.item_type == 'post')
        s = (source_type or "").lower()
        if s == "feed" or s == "native":
            stmt = stmt.where(Post.parent_post_id == None, Post.source_type == "native")
        elif s == "main":
            stmt = stmt.where(Post.parent_post_id == None, Post.source_type.in_(["native", "rss", "p2p_relay", "nostr"]))
        else:
            stmt = stmt.where(Post.parent_post_id == None, Post.source_type == s)
            
        if language and language != "all":
            # Allow matching posts that have the selected language OR are unknown/default ('un', 'uk') 
            # to prevent hiding Nostr/RSS posts whose language wasn't accurately detected.
            stmt = stmt.where(Post.language.in_([language, "un", "uk"]))
            
        stmt = stmt.order_by(desc(Post.published_at)).offset(offset).limit(limit)
        post_ids_to_fetch = (await db.execute(stmt)).scalars().all()

        if not post_ids_to_fetch:
            return [], [], [], []

        fetch_stmt = select(Post).where(Post.id.in_(post_ids_to_fetch), Post.item_type == 'post').options(
            selectinload(Post.author),
            selectinload(Post.duplicates).selectinload(Post.author)
        )
        result = await db.execute(fetch_stmt)
        posts = result.scalars().all()
        
        post_map = {p.id: p for p in posts}
        scored_posts = [ (1.0, post_map[pid]) for pid in post_ids_to_fetch if pid in post_map ]
            
        return scored_posts, [], [], []
