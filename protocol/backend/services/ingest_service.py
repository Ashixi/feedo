from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Post, ContentType
from datetime import datetime
import logging

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
                image_vector=image_vector
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
                image_vector=image_vector
            )
            
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
            content_type=ContentType.TEXT,
            item_type="post"
        )
        db.add(new_post)
        await db.commit()
        
        logger.info(f"Ingested post from {post_data.source_type}: {post_data.source_specific_id}")
        return {"status": "success", "message": "Post ingested"}
