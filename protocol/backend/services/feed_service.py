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

        # If user has preferred_tags, trigger intelligent PRF logic per tag + 30% trending
        scored_posts_p2p = []
        if user and user.preferred_tags:
            # First determine target languages
            target_langs = []
            if user.preferred_languages:
                target_langs.extend([l.lower() for l in user.preferred_languages])
            if language and language != "all":
                target_langs.append(language.lower())
                
            num_tags = len(user.preferred_tags)
            limit_70 = max(1, int(limit * 0.7))
            tag_limit = max(2, limit_70 // num_tags)
            tag_offset = offset // num_tags
            
            all_rel_hash_ids = []
            seen_vectors = []
            
            # 1. Fetch 70% semantic posts using Pseudo-Relevance Feedback for EACH tag
            for tag in user.preferred_tags:
                try:
                    # Get embedding for the tag
                    vector = await brain.get_embedding_async(tag)
                    
                    # Pseudo-Relevance Feedback (PRF)
                    pr_results = brain.table.search(vector).limit(3).to_list()
                    pr_vectors = [r["vector"] for r in pr_results if "vector" in r]
                    if pr_vectors:
                        # Average vectors
                        avg_retrieved = [sum(v[i] for v in pr_vectors) / len(pr_vectors) for i in range(len(vector))]
                        vector = [0.6 * vector[i] + 0.4 * avg_retrieved[i] for i in range(len(vector))]
                        
                    # Main search
                    search_query = brain.table.search(vector)
                    
                    if target_langs:
                        # Allow target languages plus 'un' (unknown) and 'uk' (default fallback)
                        allowed_langs = set(target_langs)
                        allowed_langs.update(['un', 'uk'])
                        langs_str = ", ".join([f"'{l}'" for l in allowed_langs])
                        search_query = search_query.where(f"language IN ({langs_str})")
                        
                    # Paginate per tag
                    raw_results = search_query.limit(tag_limit + tag_offset).to_list()[tag_offset:]
                    
                    for r in raw_results:
                        if "hash_id" in r and r.get("_distance", 0) < 1.6:
                            vec = r.get("vector")
                            is_dup = False
                            if vec:
                                norm_vec = sum(v * v for v in vec) ** 0.5
                                if norm_vec > 0:
                                    for s_vec in seen_vectors:
                                        dot = sum(a * b for a, b in zip(vec, s_vec))
                                        norm_s = sum(v * v for v in s_vec) ** 0.5
                                        if norm_s > 0:
                                            cos_sim = dot / (norm_vec * norm_s)
                                            if cos_sim > 0.95:
                                                is_dup = True
                                                break
                            if not is_dup:
                                if vec:
                                    seen_vectors.append(vec)
                                if r["hash_id"] not in all_rel_hash_ids:
                                    all_rel_hash_ids.append(r["hash_id"])
                except Exception as e:
                    logger.error(f"Error in PRF search for tag '{tag}': {e}")
                    
            # 2. Fetch 30% trending posts via P2P (only on first page or adjust offset)
            limit_30 = limit - limit_70
            trending_offset = int((offset / limit) * limit_30) if limit > 0 else 0
            
            try:
                trending_results = await fetch_p2p("feed_trending", "", limit_30 + trending_offset)
                trending_results = trending_results[trending_offset:]
                for r in trending_results:
                    hid = r.get("hash_id")
                    if hid and hid not in all_rel_hash_ids:
                        all_rel_hash_ids.append(hid)
            except Exception as e:
                logger.error(f"Error fetching trending posts: {e}")
                
            if all_rel_hash_ids:
                # Optionally shuffle to mix topics nicely
                import random
                random.shuffle(all_rel_hash_ids)
                
                fetch_stmt = select(Post).where(Post.hash_id.in_(all_rel_hash_ids), Post.item_type == 'post').options(
                    selectinload(Post.author),
                    selectinload(Post.duplicates).selectinload(Post.author)
                )
                result = await db.execute(fetch_stmt)
                posts = result.scalars().all()
                
                post_map = {p.hash_id: p for p in posts}
                scored_posts_p2p = [ (1.0, post_map[hid]) for hid in all_rel_hash_ids if hid in post_map ]

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
