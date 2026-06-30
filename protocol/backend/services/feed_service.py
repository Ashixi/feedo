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
                    }, timeout=1.5)
                    if res.status_code == 200:
                        data = res.json()
                        return data.get("results", [])
            except Exception as e:
                logger.error(f"P2P search error: {e}")
            return []

        # If user has preferred_tags, trigger intelligent PRF logic per tag + 30% trending
        from models import Post, UserFeedCache
        scored_posts_p2p = []
        
        # Determine if we can use a vector search (either user tags or system default vector)
        is_text_search = bool(text and text.strip())
        has_user_tags = user and user.preferred_tags
        has_default_vector = getattr(brain, "default_vector", None) is not None
        
        if is_text_search or has_user_tags or has_default_vector:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            
            # Helper to compute the full feed
            async def compute_feed():
                try:
                    user_vector = None
                    if is_text_search:
                        user_vector = await brain.get_embedding_async(text.strip())
                    elif has_user_tags:
                        user_vector = user.user_vector
                        if not user_vector:
                            vectors = []
                            for tag in user.preferred_tags:
                                vec = await brain.get_embedding_async(tag)
                                if vec: vectors.append(vec)
                            if vectors:
                                user_vector = [sum(x) / len(vectors) for x in zip(*vectors)]
                                user.user_vector = user_vector
                                user.last_vector_updated_at = now
                                await db.commit()
                    else:
                        user_vector = brain.default_vector
                        
                    if not user_vector: return []
                    
                    # Pseudo-Relevance Feedback (PRF)
                    pr_results = brain.table.search(user_vector).limit(5).to_list()
                    pr_vectors = [r["vector"] for r in pr_results if "vector" in r]
                    if pr_vectors:
                        avg_retrieved = [sum(v[i] for v in pr_vectors) / len(pr_vectors) for i in range(len(user_vector))]
                        user_vector = [0.7 * user_vector[i] + 0.3 * avg_retrieved[i] for i in range(len(user_vector))]
                        
                    search_query = brain.table.search(user_vector)
                    
                    target_langs = []
                    if user and user.preferred_languages:
                        target_langs.extend([l.lower() for l in user.preferred_languages])
                    if language and language != "all":
                        target_langs.append(language.lower())
                        
                    if target_langs:
                        allowed_langs = set(target_langs)
                        allowed_langs.update(['un', 'uk'])
                        langs_str = ", ".join([f"'{l}'" for l in allowed_langs])
                        search_query = search_query.where(f"language IN ({langs_str})")
                        
                    # Fetch top 1000 for cache to ensure we have enough diversity if one author dominates
                    fetch_limit = 1000 if (not language or language == "all") and source_type == "main" else max(250, limit + offset)
                    raw_results = search_query.limit(fetch_limit).to_list()
                    
                    seen_hash_ids = set()
                    all_rel_hash_ids = []
                    
                    for r in raw_results:
                        if "hash_id" in r:
                            hid = r["hash_id"]
                            if hid not in seen_hash_ids:
                                seen_hash_ids.add(hid)
                                all_rel_hash_ids.append((r.get("_distance", 1.0), hid))
                                
                    # Add trending (only for main feed)
                    if source_type == "main":
                        try:
                            trending_results = await fetch_p2p("feed_trending", "", 50)
                            for r in trending_results:
                                hid = r.get("hash_id")
                                if hid and hid not in seen_hash_ids:
                                    seen_hash_ids.add(hid)
                                    all_rel_hash_ids.append((2.0, hid)) # Trending appended at end
                        except Exception as e:
                            logger.error(f"Error fetching trending: {e}")
                            
                    all_rel_hash_ids.sort(key=lambda x: x[0])
                    sorted_hashes = [x[1] for x in all_rel_hash_ids]
                    
                    if not sorted_hashes:
                        return []
                        
                    # Fetch author addresses to enforce diversity
                    fetch_stmt = select(Post.hash_id, Post.author_address).where(Post.hash_id.in_(sorted_hashes))
                    res = await db.execute(fetch_stmt)
                    author_map = {row.hash_id: row.author_address for row in res}
                    
                    diversified = []
                    backlog = []
                    recent_authors = [] # Sliding window of last 3 authors
                    author_counts = {}
                    
                    for hid in sorted_hashes:
                        if len(diversified) >= fetch_limit:
                            break
                            
                        author = author_map.get(hid)
                        if author:
                            count = author_counts.get(author, 0)
                            if count >= 4:
                                # Hard cap: absolute maximum 4 posts per author in the ENTIRE feed
                                continue
                                
                            author_counts[author] = count + 1
                            
                            # Max 1 post per author in any window of 3 posts
                            if recent_authors.count(author) >= 1:
                                backlog.append(hid)
                            else:
                                diversified.append(hid)
                                recent_authors.append(author)
                                if len(recent_authors) > 3:
                                    recent_authors.pop(0)
                        else:
                            diversified.append(hid)
                                
                    # Append backlog at the end, bounded by fetch_limit
                    final_feed = diversified + backlog
                    return final_feed[:fetch_limit]
                except Exception as e:
                    logger.error(f"Error computing feed: {e}")
                    return []
 
            # Cache logic (only for main feed without specific language filters for registered users)
            if user and (not language or language == "all") and source_type == "main":
                cache = (await db.execute(select(UserFeedCache).where(UserFeedCache.wallet_address == user.wallet_address))).scalar_one_or_none()
                needs_update = False
                
                if not cache:
                    cache = UserFeedCache(wallet_address=user.wallet_address, feed_hash_ids=[])
                    db.add(cache)
                    needs_update = True
                elif (now - cache.updated_at).total_seconds() > 600:
                    needs_update = True
                    
                if needs_update and offset == 0:
                    cache.feed_hash_ids = await compute_feed()
                    cache.updated_at = now
                    await db.commit()
                
                sorted_hash_ids = cache.feed_hash_ids[offset:offset+limit] if cache.feed_hash_ids else []
            else:
                # Bypass cache for filtered requests or anonymous users, just compute and slice immediately
                full_list = await compute_feed()
                sorted_hash_ids = full_list[offset:offset+limit] if full_list else []
                
            if sorted_hash_ids:
                fetch_stmt = select(Post).where(Post.hash_id.in_(sorted_hash_ids), Post.item_type == 'post').options(
                    selectinload(Post.author),
                    selectinload(Post.duplicates).selectinload(Post.author)
                )
                result = await db.execute(fetch_stmt)
                posts = result.scalars().all()
                
                post_map = {p.hash_id: p for p in posts}
                scored_posts_p2p = [ (1.0, post_map[hid]) for hid in sorted_hash_ids if hid in post_map ]
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
