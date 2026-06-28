from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import datetime as dt

from database import get_db
from models import Post, User
from tokenomics_service import TokenomicsService, DEVELOPER_WALLET
from main import brain
from auth import validate_zero_trust_request
import sys
import os

# Ensure utils is accessible
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.nsfw_filter import is_nsfw

router = APIRouter()

class PromoteRequest(BaseModel):
    post_hash_id: str
    budget: int
    pubkey: str
    timestamp: int
    signature: str

class SubscribeRequest(BaseModel):
    pubkey: str
    months: int = 1
    timestamp: int
    signature: str

@router.post("/promote_post")
async def promote_post(req: PromoteRequest, db: AsyncSession = Depends(get_db)):
    validate_zero_trust_request(
        wallet_address=req.pubkey,
        timestamp=req.timestamp,
        payload_dict={"post_hash_id": req.post_hash_id, "budget": req.budget},
        signature=req.signature
    )

    if req.budget < 100:
        raise HTTPException(status_code=400, detail="Minimum budget is 100 satoshis")
        
    balance_record = await TokenomicsService.get_or_create_balance(db, req.pubkey)
    if balance_record.balance < req.budget:
        raise HTTPException(status_code=400, detail="Insufficient satoshis")
        
    stmt = select(Post).where(Post.hash_id == req.post_hash_id)
    post = (await db.execute(stmt)).scalars().first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
        
    balance_record.balance -= req.budget
    post.is_promoted = True
    post.ad_budget += req.budget
    post.item_type = "promoted"
    
    await db.commit()
    
    if brain and post.text_content:
        await brain.add_vector_async(post.id, post.hash_id, post.text_content, source_type=post.source_type, item_type="promoted")
            
    return {"status": "success", "message": f"Post {req.post_hash_id} promoted with budget {req.budget} satoshis"}

@router.post("/subscribe_premium")
async def subscribe_premium(req: SubscribeRequest, db: AsyncSession = Depends(get_db)):
    validate_zero_trust_request(
        wallet_address=req.pubkey,
        timestamp=req.timestamp,
        payload_dict={"months": req.months},
        signature=req.signature
    )
    
    if req.months < 1:
        raise HTTPException(status_code=400, detail="Months must be at least 1")
        
    cost_per_month = 5000
    total_cost = cost_per_month * req.months
    
    balance_record = await TokenomicsService.get_or_create_balance(db, req.pubkey)
    if balance_record.balance < total_cost:
        raise HTTPException(status_code=400, detail="Insufficient satoshis")
        
    stmt = select(User).where(User.wallet_address == req.pubkey)
    user = (await db.execute(stmt)).scalars().first()
    if not user:
        user = User(wallet_address=req.pubkey)
        db.add(user)
        
    balance_record.balance -= total_cost
    
    now_utc = dt.datetime.now(dt.timezone.utc)
    if not user.premium_until or user.premium_until.replace(tzinfo=dt.timezone.utc) < now_utc:
        user.premium_until = now_utc + dt.timedelta(days=30 * req.months)
    else:
        user.premium_until = user.premium_until.replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=30 * req.months)
        
    await TokenomicsService.reward_peer(db, DEVELOPER_WALLET, total_cost, reason="premium_subscription")
    
    await db.commit()
    return {"status": "success", "premium_until": user.premium_until}

@router.get("/feed/smart")
async def get_smart_feed(
    request: Request, 
    wallet_address: str, 
    limit: int = 50, 
    offset: int = 0, 
    source_type: str = "main", 
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy.orm import selectinload
    from main import p2p, brain, _load_user_by_wallet, _display_author_name, _author_avatar_url
    from app_layer.feed_engine import FeedEngine
    from app_layer.ads_manager import AdsManager
    import datetime as dt

    pubkey = request.headers.get("X-P2P-Pubkey")
    if pubkey and p2p and hasattr(p2p, "reputation"):
        p2p.reputation.charge_peer(pubkey, limit)
        p2p.reputation.can_afford(pubkey, limit)

    stmt_user = select(User).where(User.wallet_address == wallet_address)
    user = (await db.execute(stmt_user)).scalar_one_or_none()
    
    if not user or not user.user_vector:
        return await get_feed(limit=limit, offset=offset, source_type=source_type, wallet_address=wallet_address, db=db)
        
    user_langs = user.preferred_languages or []
    user_geo = (user.__dict__.get('metadata_') or {}).get('geo') if hasattr(user, 'metadata_') else None
    
    now_utc = dt.datetime.now(dt.timezone.utc)
    is_premium = False
    if user.premium_until and user.premium_until.replace(tzinfo=dt.timezone.utc) > now_utc:
        is_premium = True
        
    feed_layers = await FeedEngine.generate_smart_feed(db, brain, user.user_vector, limit=limit + offset, source_type=source_type, user_languages=user_langs, user_geo=user_geo, is_premium=is_premium)
    
    rel_offset = int(offset * 0.7)
    disc_offset = offset - rel_offset
    
    rel = [pid for pid, _ in feed_layers.get("relevant", [])][rel_offset:]
    disc = [pid for pid, _ in feed_layers.get("discovery", [])][disc_offset:]
    promoted = feed_layers.get("promoted", [])
    all_target_ids = rel + disc + promoted
    
    if not all_target_ids:
        return await get_feed(limit=limit, offset=offset, source_type=source_type, wallet_address=wallet_address, db=db)
        
    stmt = select(Post).where(Post.id.in_(all_target_ids)).where(Post.text_content != None).where(Post.text_content != "")
    if source_type != "general":
        stmt = stmt.where(Post.parent_post_id == None)
    stmt = stmt.options(selectinload(Post.author), selectinload(Post.duplicates))
    result = await db.execute(stmt)
    posts = {p.id: p for p in result.scalars().all()}

    feed_response = []
    categories = [
        ("ðŸ“¢ Promoted (Ad)", [(pid, 1.0) for pid in promoted]),
        ("ðŸŽ¯ Relevant (Your interests)", feed_layers.get("relevant", [])), 
        ("ðŸ’¥ Bubble Pop (Discovery)", feed_layers.get("discovery", []))
    ]
    
    for category_name, tuples_list in categories:
        for p_id, score in tuples_list:
            p = posts.get(p_id)
            if not p: continue
            
            if is_nsfw(p.text_content):
                continue
            
            if category_name == "ðŸ“¢ Promoted (Ad)":
                await AdsManager.charge_ad_impression(db, p.id, DEVELOPER_WALLET, cost=5)

            author = p.author or await _load_user_by_wallet(db, p.author_address)
            display_author = _display_author_name(author, p.original_author_name, p.author_address)
            
            also_posted_by = []
            for dup in p.duplicates:
                also_posted_by.append({
                    "id": dup.id,
                    "source_type": dup.source_type,
                    "link": dup.external_link,
                    "published_at": dup.published_at,
                    "metadata": dup.metadata_
                })
            
            feed_response.append({
                "id": p.id,
                "recommendation_reason": category_name,
                "title": p.title, 
                "hash_id": p.hash_id,
                "content_blob_hash": p.content_blob_hash,
                "display_author": display_author,
                "source_type": p.source_type,
                "text": p.text_content,
                "content_size": p.content_size,
                "published_at": p.published_at,
                "also_posted_by": also_posted_by,
                "metadata": p.metadata_,            
                "avatar_url": _author_avatar_url(p.author),
                "sequence_number": p.sequence_number
            })
            
    return feed_response

from fastapi import Form, UploadFile, File
import base64
import httpx

@router.post("/users/upload_avatar")
async def upload_avatar(
    author_address: str = Form(...),
    signature: str = Form(...),
    hash_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    from main import verify_signature, generate_content_hash, ContentType, RUST_CORE_URL, logger, MEDIA_CACHE, _store_media_to_disk_cache
    
    author_address = author_address.strip() if author_address else ""
    hash_id = hash_id.strip() if hash_id else ""
    signature = signature.strip() if signature else ""

    stmt = select(User).where(User.wallet_address == author_address)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="ÐšÐ¾Ñ€Ð¸ÑÑ‚ÑƒÐ²Ð°Ñ‡Ð° Ð½Ðµ Ð·Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾")

    if not verify_signature(hash_id, signature, user.wallet_address):
        raise HTTPException(status_code=401, detail="Invalid signature!")

    max_media_bytes = 10 * 1024 * 1024
    content = await file.read()
    media_raw_size = len(content)
    if media_raw_size > max_media_bytes:
        raise HTTPException(status_code=400, detail="ÐœÐ°ÐºÑÐ¸Ð¼ÑƒÐ¼ 10 ÐœÐ‘")

    b64_text = base64.b64encode(content).decode('utf-8')
    media_hash = generate_content_hash(b64_text)
    media_size = media_raw_size
    media_b64_size = len(b64_text.encode('utf-8'))
    media_name = file.filename
    media_mime_type = file.content_type

    stmt_media = select(Post).where(Post.content_blob_hash == media_hash)
    existing_media = (await db.execute(stmt_media)).scalars().first()

    media_meta = {
        "media_name": media_name,
        "media_mime_type": media_mime_type,
        "media_size": media_raw_size,
        "media_b64_size": media_b64_size,
    }

    if existing_media:
        existing_media.content_size = media_size
        existing_media.metadata_ = media_meta
        existing_media.author_address = author_address
        existing_media.content_type = ContentType.IMAGE
        existing_media.is_full_content_loaded = False
        existing_media.text_content = ""
        existing_media.content_blob_hash = media_hash
        existing_media.hash_id = media_hash
    else:
        media_post = Post(
            source_type="media_blob",
            text_content="",
            content_size=media_size,
            is_full_content_loaded=False,
            author_address=author_address,
            content_blob_hash=media_hash,
            hash_id=media_hash,
            metadata_=media_meta,
            content_type=ContentType.IMAGE,
        )
        db.add(media_post)

    await db.commit()

    try:
        async with httpx.AsyncClient() as client:
            import feedo_pb2
            pb_req = feedo_pb2.PublishRequest(
                text=b64_text,
                author=author_address,
                signature=signature,
                hash_id=media_hash,
                content_blob_hash=media_hash,
                prev_post_hash="",
                sequence_number=0,
                skip_dht_upload=False
            )
            await client.post(
                RUST_CORE_URL, 
                content=pb_req.SerializeToString(),
                headers={"Content-Type": "application/x-protobuf"},
                timeout=15.0
            )
    except Exception as e:
        logger.warning(f"Failed to seed media to DHT: {e}")

    try:
        MEDIA_CACHE[media_hash] = {
            "bytes": content,
            "mime": media_mime_type or "application/octet-stream",
            "size": media_raw_size,
        }
        _store_media_to_disk_cache(media_hash, content)
    except Exception:
        logger.warning("Failed to populate MEDIA_CACHE for avatar %s", media_hash)

    return {"status": "success", "media_hash": media_hash}



from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlalchemy import desc, func
import datetime
from datetime import timezone
import random
import difflib
import asyncio

@router.get("/feed/basic")
async def get_feed(limit: int = 50, offset: int = 0, source_type: str = "main", wallet_address: str | None = None, request: Request = None, db: AsyncSession = Depends(get_db)):
    from main import p2p, brain, _require_server_variant, EXPOSE_VECTOR_API, VECTOR_API_ADDR, VECTOR_API_KEY, _load_user_by_wallet, _display_author_name, logger, _author_avatar_url
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
            meta = p.metadata_ if isinstance(p.metadata_, dict) else {}
            kind = meta.get('kind') if meta else None
            if kind not in (1, 30023):
                continue
            
        base_score = 1.0
        dup_count = len(p.duplicates)
        popularity_boost = dup_count * 0.5
        pub_date = p.published_at or datetime.datetime.now(timezone.utc).replace(tzinfo=None)
        age_hours = (datetime.datetime.now(timezone.utc).replace(tzinfo=None) - pub_date).total_seconds() / 3600.0
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
        display_author = _display_author_name(author, p.original_author_name, p.author_address)
        
        also_posted_by = []
        for dup in p.duplicates:
            dup_author_obj = dup.author or await _load_user_by_wallet(db, dup.author_address)
            dup_author = _display_author_name(dup_author_obj, dup.original_author_name, dup.author_address)
            also_posted_by.append({
                "id": dup.id,
                "source_type": dup.source_type,
                "link": dup.external_link,
                "published_at": dup.published_at,
                "metadata": dup.metadata_,
                "text": dup.text_content,
                "display_author": dup_author,
                "author_address": dup.author_address,
                "avatar_url": _author_avatar_url(dup_author_obj),
                "is_repost": dup.is_repost,
            })
            
        reason = None
        if wallet_address and p.is_repost and p.author_address == wallet_address:
            reason = "Duplicate"
        elif p.hash_id in rel_hash_id_set:
            reason = "Ð—Ð° Ð²Ð°ÑˆÐ¸Ð¼Ð¸ Ñ–Ð½Ñ‚ÐµÑ€ÐµÑÐ°Ð¼Ð¸"
        elif p.hash_id in disc_hash_id_set:
            reason = "Anti-bubble"
        elif p.id in rand_res_set:
            reason = "Random discovery"
        relay_list = []
        meta = p.metadata_ if isinstance(p.metadata_, dict) else {}
        if getattr(p, "relay_url", None):
            relay_list.append(p.relay_url)
        elif meta and meta.get("relay"):
            relay_list.append(meta.get("relay"))
            
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
            "avatar_url": _author_avatar_url(p.author)
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
                        
                dup_author = _display_author_name(rand_dup.author, rand_dup.original_author_name, rand_dup.author_address)
                dup_dict = dict(post_dict)
                dup_dict["id"] = rand_dup.id
                dup_dict["text"] = rand_dup.text_content
                dup_dict["display_author"] = dup_author
                dup_dict["author_address"] = rand_dup.author_address
                dup_dict["avatar_url"] = _author_avatar_url(rand_dup.author)
                dup_dict["recommendation_reason"] = "Ð†Ð½ÑˆÐ° Ð´ÑƒÐ¼ÐºÐ° Ð½Ð° Ñ†ÑŽ Ñ‚ÐµÐ¼Ñƒ"
                
                copy_also_posted = []
                orig_author = _display_author_name(p.author, p.original_author_name, p.author_address)
                copy_also_posted.append({
                    "id": p.id,
                    "source_type": p.source_type,
                    "link": p.external_link,
                    "published_at": p.published_at,
                    "metadata": p.metadata_,
                    "text": p.text_content,
                    "display_author": orig_author,
                    "author_address": p.author_address,
                    "avatar_url": _author_avatar_url(p.author),
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

@router.get("/feed/profile/{target_wallet_address}")
async def get_profile_feed(target_wallet_address: str, limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    from main import _display_author_name, _author_avatar_url
    
    stmt = (
        select(Post)
        .options(selectinload(Post.author))
        .where(Post.author_address == target_wallet_address, Post.parent_post_id == None)
        .order_by(Post.published_at.desc())
        .offset(offset)
        .limit(limit)
    )
    
    posts = (await db.execute(stmt)).scalars().all()
    
    feed_response = []
    for p in posts:
        display_author = _display_author_name(p.author, None, p.author_address)
        
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
            "recommendation_reason": "ÐŸÑ€Ð¾Ñ„Ñ–Ð»ÑŒ ÐºÐ¾Ñ€Ð¸ÑÑ‚ÑƒÐ²Ð°Ñ‡Ð°",
            "metadata": p.metadata_ or {}, 
            "user_liked": False,
            "user_saved": False,
            "relay_urls": [],
            "also_posted_by": [],
            "avatar_url": _author_avatar_url(p.author)
        }
        feed_response.append(post_dict)
        
    return feed_response

class DeletePostRequest(BaseModel):
    wallet_address: str
    post_id: int
    timestamp: int
    signature: str


@router.post("/posts/delete")
async def delete_post(req: DeletePostRequest, db: AsyncSession = Depends(get_db)):
    from main import validate_zero_trust_request, _to_naive_utc
    validate_zero_trust_request(
        wallet_address=req.wallet_address,
        timestamp=req.timestamp,
        payload_dict={"post_id": req.post_id},
        signature=req.signature
    )
    
    stmt = select(Post).where(Post.id == req.post_id)
    post = (await db.execute(stmt)).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="ÐŸÐ¾ÑÑ‚ Ð½Ðµ Ð·Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾")
        
    post_author = post.author_address or ""
    req_author = req.wallet_address
    if post_author.startswith("0x"): post_author = post_author[2:]
    if req_author.startswith("0x"): req_author = req_author[2:]
    if post_author.lower() != req_author.lower():
        raise HTTPException(status_code=403, detail="Ð’Ð¸ Ð½Ðµ Ñ” Ð°Ð²Ñ‚Ð¾Ñ€Ð¾Ð¼ Ñ†ÑŒÐ¾Ð³Ð¾ Ð¿Ð¾ÑÑ‚Ð°")
        
    now_ts = datetime.datetime.now(timezone.utc).timestamp()
    pub_ts = _to_naive_utc(post.published_at).replace(tzinfo=timezone.utc).timestamp()
    if (now_ts - pub_ts) > 900:
        raise HTTPException(status_code=400, detail="Ð§Ð°Ñ Ð´Ð»Ñ Ð²Ð¸Ð´Ð°Ð»ÐµÐ½Ð½Ñ Ð¿Ð¾ÑÑ‚Ð° (15 Ñ…Ð²Ð¸Ð»Ð¸Ð½) Ð·Ð°ÐºÑ–Ð½Ñ‡Ð¸Ð²ÑÑ")
        
    if post.is_finalized:
        raise HTTPException(status_code=400, detail="Ð¦ÐµÐ¹ Ð¿Ð¾ÑÑ‚ Ð²Ð¶Ðµ Ñ„Ñ–Ð½Ð°Ð»Ñ–Ð·Ð¾Ð²Ð°Ð½Ð¾ Ð² Ð±Ð»Ð¾ÐºÑ‡ÐµÐ¹Ð½Ñ– Ñ– Ð¹Ð¾Ð³Ð¾ Ð½Ðµ Ð¼Ð¾Ð¶Ð½Ð° Ð²Ð¸Ð´Ð°Ð»Ð¸Ñ‚Ð¸")
        
    await db.delete(post)
    await db.commit()
    return {"status": "success", "message": "ÐŸÐ¾ÑÑ‚ Ð²Ð¸Ð´Ð°Ð»ÐµÐ½Ð¾"}

from media_storage import get_media_storage
from fastapi import Response

@router.post("/e2ee/media/upload")
async def upload_encrypted_media(
    file: UploadFile = File(...)
):
    storage = get_media_storage()
    data = await file.read()
    media_id = await storage.upload(data, file.content_type)
    return {"status": "success", "media_id": media_id}

@router.get("/e2ee/media/download/{media_id}")
async def download_encrypted_media(media_id: str):
    storage = get_media_storage()
    data = await storage.download(media_id)
    if not data:
        raise HTTPException(status_code=404, detail="Media not found")
    return Response(content=data, media_type="application/octet-stream")

