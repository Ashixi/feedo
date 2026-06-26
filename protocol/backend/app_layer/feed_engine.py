import math
from datetime import datetime, timezone
from sqlalchemy import select
from models import Post

class FeedEngine:
    @staticmethod
    async def generate_smart_feed(db, brain, user_vector: list[float], limit: int = 50, source_type: str = "main", user_languages: list[str] | None = None, user_geo: str | None = None, is_premium: bool = False) -> dict:
        if not user_vector:
            return {"relevant": [], "discovery": [], "promoted": []}

        # Dynamically calculate how many raw posts to fetch to ensure we have enough after filtering
        # limit passed here is actually limit + offset
        search_limit = max(300, int(limit * 3))
        
        # 1. Fetch raw posts from Core Protocol (vector db)
        results = brain.semantic_search(user_vector, limit=search_limit, source_type=source_type)
        
        # 2. Fetch promoted posts from Core Protocol
        promoted_results = []
        if not is_premium:
            promoted_results = brain.semantic_search(user_vector, limit=10, item_type="promoted")

        promoted_ids = []
        
        # Process promoted posts
        for res in promoted_results:
            post_id = res.get("post_id")
            if post_id:
                similarity = 1.0 - (res.get("distance", 2.0) / 2.0)
                if similarity > 0.5: # Ads must be somewhat relevant
                    promoted_ids.append(post_id)
                if len(promoted_ids) >= 3: # Max 3 ads per request
                    break

        # 3. Retrieve engagement and age metrics from PostgreSQL for the semantic matches
        # results have 'hash_id' and 'post_id'. We will query by hash_id.
        hash_ids = [res.get("hash_id") for res in results if res.get("hash_id")]
        
        db_posts = []
        if hash_ids:
            # Chunk the query if needed, but 300 is fine for PostgreSQL IN clause
            stmt = select(Post.hash_id, Post.published_at, Post.metadata_).where(Post.hash_id.in_(hash_ids))
            db_res = await db.execute(stmt)
            db_posts = db_res.all()
            
        # Create a lookup map
        post_meta_map = {
            row.hash_id: {
                "published_at": row.published_at,
                "metadata": row.metadata_ or {}
            } for row in db_posts
        }

        user_langs = [l.lower() for l in (user_languages or [])]
        
        scored_posts = []
        
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        for res in results:
            post_id = res.get("post_id")
            hash_id = res.get("hash_id")
            if not post_id or not hash_id:
                continue
                
            # Base semantic similarity score
            similarity = 1.0 - (res.get("distance", 2.0) / 2.0)
            
            # Geo/Language weights
            lang = (res.get("language") or "").lower()
            geo = (res.get("geo") or "")

            if user_langs:
                if lang in user_langs:
                    lang_w = 1.0
                elif not lang:
                    lang_w = 0.9
                else:
                    lang_w = 0.5
            else:
                lang_w = 1.0

            if user_geo and geo:
                if geo == user_geo:
                    geo_w = 1.2
                elif geo.split("-")[0] == user_geo.split("-")[0]:
                    geo_w = 1.05
                else:
                    geo_w = 0.6
            else:
                geo_w = 1.0

            base_score = similarity * lang_w * geo_w
            
            # Apply Social Engagement & Time Decay
            engagement_multiplier = 1.0
            time_decay = 1.0
            
            meta_info = post_meta_map.get(hash_id)
            if meta_info:
                metadata = meta_info["metadata"]
                likes = metadata.get("likes", 0)
                reposts = metadata.get("reposts", 0)
                zaps = metadata.get("tips", 0) # Tips = zaps
                
                # Multiplier cap at 3.0
                engagement_bonus = 1.0 + (likes * 0.05) + (reposts * 0.1) + (zaps * 0.25)
                engagement_multiplier = min(3.0, engagement_bonus)
                
                published_at = meta_info["published_at"]
                if published_at:
                    # Calculate age in hours
                    age_hours = (now_utc - published_at).total_seconds() / 3600.0
                    # Decay formula: half-life of roughly 50 hours
                    # math.exp(-0.014 * age_hours)
                    if age_hours > 0:
                        time_decay = math.exp(-0.014 * age_hours)
                    else:
                        time_decay = 1.0

            final_score = base_score * engagement_multiplier * time_decay
            scored_posts.append({
                "post_id": post_id,
                "score": final_score
            })
            
        # Sort by final Global Quality Score descending
        scored_posts.sort(key=lambda x: x["score"], reverse=True)
        
        relevant_ids = []
        discovery_ids = []
        
        rel_target = int(limit * 0.7)
        disc_target = int(limit * 0.3)
        
        for item in scored_posts:
            pid = item["post_id"]
            sc = item["score"]
            if sc > 0.65 and len(relevant_ids) < rel_target:
                relevant_ids.append((pid, sc))
            elif 0.2 < sc <= 0.65 and len(discovery_ids) < disc_target:
                discovery_ids.append((pid, sc))
                
            if len(relevant_ids) >= rel_target and len(discovery_ids) >= disc_target:
                break

        return {"relevant": relevant_ids, "discovery": discovery_ids, "promoted": promoted_ids}
