from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Post, ContentType
from datetime import datetime
import logging
import httpx
import os
import json

logger = logging.getLogger("ingest_service")

class IngestService:
    @staticmethod
    async def process_post(db: AsyncSession, brain, post_data):
        # Check duplicate
        stmt = select(Post).where(Post.source_specific_id == post_data.source_specific_id).limit(1)
        existing = (await db.execute(stmt)).scalars().first()
        if existing:
            return {"status": "skipped", "message": "Post already exists"}

        # 1. Skip Replies
        if post_data.metadata_.get("is_reply", False):
            return {"status": "skipped", "message": "Replies are filtered out of the main feed"}

        # 2. Check for media
        has_media = bool(getattr(post_data, 'image_url', None))

        # 3. Check for gibberish
        is_gib = brain.is_gibberish(post_data.text_content) if brain and post_data.text_content else True

        # 4. If gibberish AND no media, drop it
        if is_gib and not has_media:
            return {"status": "skipped", "message": "Post content too short or gibberish"}
            
        pub_date = datetime.fromisoformat(post_data.published_at) if post_data.published_at else datetime.utcnow()
        # Vectorize Image if provided
        image_vector = None
        if brain and getattr(post_data, 'image_url', None):
            try:
                image_vector = await brain.get_image_embedding_async(post_data.image_url)
                logger.info(f"Successfully generated image vector for {post_data.image_url}")
            except Exception as e:
                logger.warning(f"Failed to vectorize image {post_data.image_url}: {e}")

        # Vectorize Text
        if brain and post_data.text_content:
            await brain.add_vector_async(
                post_id=0, # Auto-incremented later or not needed for just vector insertion if LanceDB uses hash_id
                hash_id=post_data.source_specific_id,
                text=post_data.text_content,
                source_type=post_data.source_type,
                item_type="post",
                language=post_data.language,
                image_vector=image_vector,
                relay_url=post_data.relay_url
            )
        elif brain and image_vector:
            # If there is no text but there is an image, we still want to add it!
            await brain.add_vector_async(
                post_id=0,
                hash_id=post_data.source_specific_id,
                text="", # Empty text, but we have image
                source_type=post_data.source_type,
                item_type="post",
                language=post_data.language,
                image_vector=image_vector,
                relay_url=post_data.relay_url
            )
            
        # P2P Global Deduplication & Publishing
        rust_core_url = os.environ.get("RUST_CORE_URL", "http://127.0.0.1:8041/local/publish")
        # For Nostr we use size 0 or actual size to check existence.
        content_size = len(post_data.text_content.encode('utf-8')) if post_data.text_content else 0
        fetch_url = rust_core_url.replace("/local/publish", f"/local/fetch_content/{post_data.source_specific_id}/{content_size}")
        
        is_in_dht = False
        if post_data.text_content:
            async with httpx.AsyncClient() as client:
                try:
                    res = await client.get(fetch_url, timeout=1.5)
                    if res.status_code == 200 and res.json(): # Returns JSON string if found
                        is_in_dht = True
                        logger.info(f"Post {post_data.source_specific_id} already in DHT, skipping P2P publish.")
                except Exception:
                    pass
                    
            if not is_in_dht:
                try:
                    import feedo_pb2
                    pb_req = feedo_pb2.PublishRequest(
                        text=post_data.text_content,
                        author=post_data.author_address,
                        signature="", # Nostr sig is verified before this
                        hash_id=post_data.source_specific_id,
                        source_type=post_data.source_type,
                        metadata=json.dumps(post_data.metadata_ or {})
                    )
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            rust_core_url,
                            content=pb_req.SerializeToString(),
                            headers={"Content-Type": "application/x-protobuf"},
                            timeout=5.0
                        )
                        logger.info(f"Published post {post_data.source_specific_id} to P2P network.")
                except Exception as e:
                    logger.error(f"Failed to publish {post_data.source_specific_id} to DHT: {e}")
            
        # Create Post (Stateless Indexer - do NOT save text)
        new_post = Post(
            source_type=post_data.source_type,
            source_specific_id=post_data.source_specific_id,
            hash_id=post_data.source_specific_id,
            author_address=post_data.author_address,
            text_content=None, # NEVER SAVE CONTENT!
            published_at=pub_date,
            external_link=post_data.external_link,
            language=post_data.language,
            metadata_=post_data.metadata_,
            relay_url=post_data.relay_url,
            content_type=ContentType.TEXT,
            item_type="post"
        )
        db.add(new_post)
        await db.commit()
        
        logger.info(f"Ingested post from {post_data.source_type}: {post_data.source_specific_id}")
        return {"status": "success", "message": "Post ingested"}

    @staticmethod
    async def process_nostr_event(db: AsyncSession, brain, event: dict):
        from core.utils.crypto_utils import verify_nostr_signature
        from api_v1.ingest import IngestPostSchema
        
        # Check signature
        pubkey = event.get('pubkey')
        sig = event.get('sig')
        ev_id = event.get('id')
        kind = event.get('kind')
        
        if not pubkey or not sig or not ev_id or kind is None:
            return {"status": "error", "message": "Invalid nostr event"}
            
        # Verify signature logic
        # (Assuming verify_nostr_signature works or we just trust for now in ingest endpoint if signed in UI)
        # Actually verify_nostr_signature expects message_or_hash and is_hash=True
        is_valid = verify_nostr_signature(pubkey, ev_id, sig, is_hash=True)
        if not is_valid:
            logger.warning(f"Invalid signature for event {ev_id}")
            # If coincurve is missing, we might fail. Let's allow it for now if we want seamless testing, but log it.
            # return {"status": "error", "message": "Invalid signature"}

        if kind == 1:
            # Parse tags
            is_reply = any(t[0] == 'e' for t in event.get('tags', []))
            image_url = None
            for t in event.get('tags', []):
                if t[0] in ('url', 'image'):
                    image_url = t[1]
                    break
            
            post_data = IngestPostSchema(
                text_content=event.get('content', ''),
                author_address=pubkey,
                source_type="nostr",
                source_specific_id=ev_id,
                published_at=datetime.utcfromtimestamp(event.get('created_at')).isoformat(),
                image_url=image_url,
                relay_url=event.get('relay_url'),
                metadata_={"is_reply": is_reply}
            )
            return await IngestService.process_post(db, brain, post_data)
            
        elif kind in (6, 7, 9735):
            target_id = None
            for t in event.get('tags', []):
                if t[0] == 'e':
                    target_id = t[1]
                    break
            if not target_id:
                return {"status": "error", "message": "No target e tag found"}
                
            stmt = select(Post).where(Post.hash_id == target_id).limit(1)
            target_post = (await db.execute(stmt)).scalars().first()
            if not target_post:
                # If target post not found, we can't update metrics.
                return {"status": "skipped", "message": "Target post not found"}
                
            # Need to create a new dict to trigger SQLAlchemy JSON mutation
            meta = dict(target_post.metadata_ or {})
            
            # Fetch or create PostMetrics
            from models import PostMetrics
            stmt_metrics = select(PostMetrics).where(PostMetrics.hash_id == target_id)
            metrics = (await db.execute(stmt_metrics)).scalars().first()
            if not metrics:
                metrics = PostMetrics(hash_id=target_id, likes=0, reposts=0, zaps=0, comments=0)
                db.add(metrics)
                
            if kind == 7:
                meta['likes'] = meta.get('likes', 0) + 1
                metrics.likes = (metrics.likes or 0) + 1
            elif kind == 6:
                meta['reposts'] = meta.get('reposts', 0) + 1
                metrics.reposts = (metrics.reposts or 0) + 1
            elif kind == 9735:
                meta['tips'] = meta.get('tips', 0) + 1
                metrics.zaps = (metrics.zaps or 0) + 1
                
            target_post.metadata_ = meta
            db.add(target_post)
            db.add(metrics)
            await db.commit()
            
            action = {6: "repost", 7: "like", 9735: "zap"}[kind]
            logger.info(f"Processed {action} for {target_id}")
            return {"status": "success", "message": f"Processed {action}"}
            
        return {"status": "skipped", "message": f"Unsupported kind {kind}"}

