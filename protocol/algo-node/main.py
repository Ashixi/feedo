import os
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("algo-node")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/feedo")
engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

app = FastAPI(title="Feedo Algorithm Service")

async def calculate_trending_scores():
    while True:
        try:
            logger.info("Running trending score calculation...")
            async with SessionLocal() as db:
                # Basic formula: (likes * 1 + zaps * 5 + reposts * 2 + comments * 3) / (age_in_hours + 2)^1.5
                # Using Post.published_at for age.
                # Since we don't have all data in PostMetrics, we join with posts
                query = text("""
                    UPDATE post_metrics
                    SET trending_score = (
                        COALESCE(post_metrics.likes, 0) * 1.0 + 
                        COALESCE(post_metrics.zaps, 0) * 5.0 + 
                        COALESCE(post_metrics.reposts, 0) * 2.0 + 
                        COALESCE(post_metrics.comments, 0) * 3.0
                    ) / POWER(
                        EXTRACT(EPOCH FROM (NOW() - p.published_at))/3600.0 + 2.0, 
                        1.5
                    ),
                    velocity = (COALESCE(post_metrics.likes, 0) + COALESCE(post_metrics.zaps, 0)) / 
                               (EXTRACT(EPOCH FROM (NOW() - p.published_at))/3600.0 + 0.1)
                    FROM posts p
                    WHERE p.hash_id = post_metrics.hash_id
                    AND p.published_at >= NOW() - INTERVAL '7 days'
                """)
                await db.execute(query)
                await db.commit()
            logger.info("Trending score calculation finished.")
        except Exception as e:
            logger.error(f"Error calculating trending scores: {e}")
            
        await asyncio.sleep(60) # Run every minute

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(calculate_trending_scores())

@app.get("/health")
async def health():
    return {"status": "ok"}
