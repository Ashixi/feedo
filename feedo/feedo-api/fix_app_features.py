import re

path = 'api_v1/app_features.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# We know the function definition starts with:
# @router.get("/feed/basic")
# async def get_feed(limit: int = 50, ...

# We will split the file into two parts: before get_feed, and after get_feed (class DeletePostRequest)
start_str = '@router.get("/feed/basic")'
end_str = 'class DeletePostRequest(BaseModel):'

start_idx = content.find(start_str)
end_idx = content.find(end_str)

if start_idx == -1 or end_idx == -1:
    print("Could not find start or end bounds.")
    exit(1)

new_get_feed = """@router.get("/feed/basic")
async def get_feed(limit: int = 50, offset: int = 0, source_type: str = "main", wallet_address: str | None = None, request: Request = None, db: AsyncSession = Depends(get_db)):
    from main import p2p, brain, _require_server_variant, EXPOSE_VECTOR_API, VECTOR_API_ADDR, VECTOR_API_KEY, _load_user_by_wallet, _display_author_name, logger
    _require_server_variant()
    if request:
        pubkey = request.headers.get("X-P2P-Pubkey")
        if pubkey and hasattr(p2p, "reputation"):
            p2p.reputation.charge_peer(pubkey, limit)
            p2p.reputation.can_afford(pubkey, limit)

    user = None
    liked_set = set()
    saved_set = set()
    if wallet_address:
        user = (await db.execute(select(User).where(User.wallet_address == wallet_address))).scalar_one_or_none()

    post_ids_to_fetch = set()
    fetched_ai_count = 0
    num_random = 0
    rand_res = []
    rel_hash_ids: list[str] = []
    disc_hash_ids: list[str] = []
    
    if user and user.user_vector:
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
        
        peer_addrs = set()
        if EXPOSE_VECTOR_API:
            stmt_peers = select(Post.metadata_).where(Post.metadata_.is_not(None)).order_by(desc(Post.published_at)).limit(200)
            peer_metas = (await db.execute(stmt_peers)).scalars().all()
            for meta in peer_metas:
                if isinstance(meta, dict) and "vector_api_addr" in meta:
                    addr = meta["vector_api_addr"]
                    if addr and addr != VECTOR_API_ADDR:
                        peer_addrs.add(addr)
                        
            if len(peer_addrs) > 10:
                peer_addrs = set(list(peer_addrs)[:10]) 

            async def fetch_peer_vectors(addr):
                try:
                    async with httpx.AsyncClient() as client:
                        headers = {}
                        if VECTOR_API_KEY:
                            headers["x-vector-api-key"] = VECTOR_API_KEY
                        resp = await client.post(
                            f"{addr}/internal/vector/query",
                            json={"vector": user.user_vector, "k": limit, "threshold": 0.65},
                            headers=headers,
                            timeout=0.5
                        )
                        if resp.status_code == 200:
                            return resp.json()
                except Exception as e:
                    logger.debug(f"Failed to query peer {addr}: {e}")
                return []

            if peer_addrs:
                tasks = [fetch_peer_vectors(addr) for addr in peer_addrs]
                peer_responses = await asyncio.gather(*tasks)
                remote_hash_ids = set()
                for p_res in peer_responses:
                    for item in p_res:
                        remote_hash_ids.add(item["hash_id"])
                        
                if remote_hash_ids:
                    stmt_remote = select(Post.id).where(Post.hash_id.in_(remote_hash_ids))
                    local_ids_for_remote = (await db.execute(stmt_remote)).scalars().all()
                    post_ids_to_fetch.update(local_ids_for_remote)
        
        fetched_ai_count = len(post_ids_to_fetch)
        
        num_random = max(1, int(limit * 0.03))
        rand_stmt = select(Post.id).where(Post.parent_post_id == None)
        if source_type != "main" and source_type != "general":
            rand_stmt = rand_stmt.where(Post.source_type == source_type)
        if post_ids_to_fetch:
            rand_stmt = rand_stmt.where(~Post.id.in_(post_ids_to_fetch))
        rand_stmt = rand_stmt.order_by(func.random()).limit(num_random)
        rand_res = (await db.execute(rand_stmt)).scalars().all()
        post_ids_to_fetch.update(rand_res)

        try:
            if (source_type or '').lower() == 'general':
                rss_stmt = select(Post.id).where(Post.source_type == 'rss', Post.parent_post_id == None).order_by(desc(Post.published_at)).limit(10)
                rss_ids = (await db.execute(rss_stmt)).scalars().all()
                post_ids_to_fetch.update(rss_ids)
        except Exception:
            pass
    
    if fetched_ai_count == 0:
        stmt = select(Post.id)
        s = (source_type or "").lower()
        if s == "general":
            stmt = stmt.where(Post.source_type.in_(["native", "rss"]))
        elif s == "feed" or s == "native":
            stmt = stmt.where(Post.parent_post_id == None, Post.source_type == "native")
        elif s == "main":
            stmt = stmt.where(Post.parent_post_id == None, Post.source_type.in_(["native", "rss", "p2p_relay"]))
        else:
            stmt = stmt.where(Post.parent_post_id == None, Post.source_type == s)
        stmt = stmt.order_by(desc(Post.published_at)).offset(offset).limit(limit)
        fallback_ids = (await db.execute(stmt)).scalars().all()
        post_ids_to_fetch.update(fallback_ids)

    if not post_ids_to_fetch:
        return []

    stmt = select(Post).where(Post.id.in_(post_ids_to_fetch), Post.item_type != 'profile').options(
        selectinload(Post.author),
        selectinload(Post.duplicates).selectinload(Post.author)
    )
    result = await db.execute(stmt)
    posts = result.scalars().all()
    scored_posts = []
    for p in posts:
        if p.item_type == 'profile':
            continue
            
        if is_nsfw(p.text_content):
            continue
            
        if p.source_type == 'nostr':
            kind = p.metadata_.get('kind') if p.metadata_ else None
            if kind not in (1, 30023):
                continue
            
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
    
    feed_response = []
    additional_perspective_posts = []
    
    rel_hash_id_set = set(rel_hash_ids)
    disc_hash_id_set = set(disc_hash_ids)
    rand_res_set = set(rand_res) if 'rand_res' in locals() else set()
    
    for score, p in scored_posts:
        author = p.author or await _load_user_by_wallet(db, p.author_address)
        display_author = p.original_author_name if p.original_author_name else _display_author_name(author, p.author_address)
        
        also_posted_by = []
        for dup in p.duplicates:
            dup_author_obj = dup.author or await _load_user_by_wallet(db, dup.author_address)
            dup_author = dup.original_author_name if dup.original_author_name else _display_author_name(dup_author_obj, dup.author_address)
            also_posted_by.append({
                "id": dup.id,
                "source_type": dup.source_type,
                "link": dup.external_link,
                "published_at": dup.published_at,
                "metadata": dup.metadata_,
                "text": dup.text_content,
                "display_author": dup_author,
                "author_address": dup.author_address,
                "avatar_url": f"/p2p-media/{dup_author_obj.avatar_media_hash}" if dup_author_obj and dup_author_obj.avatar_media_hash else None,
                "is_repost": dup.is_repost,
            })
            
        reason = None
        if wallet_address and p.is_repost and p.author_address == wallet_address:
            reason = "Duplicate"
        elif p.hash_id in rel_hash_id_set:
            reason = "За вашими інтересами"
        elif p.hash_id in disc_hash_id_set:
            reason = "Anti-bubble"
        elif p.id in rand_res_set:
            reason = "Random discovery"
        relay_list = []
        if getattr(p, "relay_url", None):
            relay_list.append(p.relay_url)
        elif p.metadata_ and p.metadata_.get("relay"):
            relay_list.append(p.metadata_.get("relay"))
            
        post_dict = {
            "id": p.id,
            "title": p.title, 
            "hash_id": p.hash_id,
            "content_blob_hash": p.content_blob_hash,
            "prev_post_hash": p.prev_post_hash,
            "sequence_number": p.sequence_number,
            "signature": p.signature,
            "author_address": p.author_address,
            "display_author": display_author,
            "source_type": p.source_type, 
            "item_type": p.item_type,
            "text": p.text_content,
            "content_size": p.content_size,
            "is_full": p.is_full_content_loaded,
            "published_at": p.published_at,
            "is_finalized": p.is_finalized,
            "is_verified": p.is_verified,
            "is_repost": p.is_repost,
            "recommendation_reason": reason,
            "metadata": p.metadata_, 
            "user_liked": (p.id in liked_set),
            "user_saved": (p.id in saved_set),
            "relay_urls": relay_list,
            "also_posted_by": also_posted_by,
            "avatar_url": f"/p2p-media/{p.author.avatar_media_hash}" if p.author and p.author.avatar_media_hash else None
        }
        
        feed_response.append(post_dict)
        
        dup_count = len(p.duplicates)
        perspectives_to_add = 0
        if dup_count > 4: perspectives_to_add = 1
        if dup_count >= 15: perspectives_to_add = 2
        if dup_count >= 30: perspectives_to_add = 4
        if dup_count >= 50: perspectives_to_add = 5
        if dup_count >= 100: perspectives_to_add = 7
        
        if perspectives_to_add > 0:
            available_dups = list(p.duplicates)
            random.shuffle(available_dups)
            added = 0
            for rand_dup in available_dups:
                if added >= perspectives_to_add:
                    break
                    
                if p.text_content and rand_dup.text_content:
                    similarity = difflib.SequenceMatcher(None, p.text_content, rand_dup.text_content).ratio()
                    if similarity > 0.85:
                        continue
                        
                dup_author = rand_dup.original_author_name if rand_dup.original_author_name else _display_author_name(rand_dup.author, rand_dup.author_address)
                dup_dict = dict(post_dict)
                dup_dict["id"] = rand_dup.id
                dup_dict["text"] = rand_dup.text_content
                dup_dict["display_author"] = dup_author
                dup_dict["author_address"] = rand_dup.author_address
                dup_dict["avatar_url"] = f"/p2p-media/{rand_dup.author.avatar_media_hash}" if rand_dup.author and rand_dup.author.avatar_media_hash else None
                dup_dict["recommendation_reason"] = "Інша думка на цю тему"
                
                copy_also_posted = []
                orig_author = p.original_author_name if p.original_author_name else _display_author_name(p.author, p.author_address)
                copy_also_posted.append({
                    "id": p.id,
                    "source_type": p.source_type,
                    "link": p.external_link,
                    "published_at": p.published_at,
                    "metadata": p.metadata_,
                    "text": p.text_content,
                    "display_author": orig_author,
                    "author_address": p.author_address,
                    "avatar_url": f"/p2p-media/{p.author.avatar_media_hash}" if p.author and p.author.avatar_media_hash else None,
                    "is_repost": p.is_repost,
                })
                for dup_info in post_dict["also_posted_by"]:
                    if dup_info["id"] != rand_dup.id:
                        copy_also_posted.append(dup_info)
                        
                dup_dict["also_posted_by"] = copy_also_posted
                additional_perspective_posts.append((dup_dict, p.id))
                added += 1

    for ap, orig_id in additional_perspective_posts:
        orig_idx = next((i for i, item in enumerate(feed_response) if item["id"] == orig_id), 0)
        min_insert_idx = orig_idx + 1
        
        if min_insert_idx < len(feed_response):
            insert_idx = random.randint(min_insert_idx, len(feed_response))
        else:
            insert_idx = len(feed_response)
            
        feed_response.insert(insert_idx, ap)

    if offset > 0 or limit > 0:
        return feed_response[offset: offset + limit]

    return feed_response

"""

new_content = content[:start_idx] + new_get_feed + content[end_idx:]

with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Fixed app_features.py!")
