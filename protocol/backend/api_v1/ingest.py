from fastapi import APIRouter, Depends, HTTPException, Security, status, Request
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models import Post, ContentType
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()

INGEST_API_KEY = os.getenv("INGEST_API_KEY", "feedo_default_ingest_key_2026")
api_key_header = APIKeyHeader(name="X-Ingest-Key", auto_error=True)

async def verify_ingest_key(api_key: str = Security(api_key_header)):
    if api_key != INGEST_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Ingest API Key")
    return api_key

class IngestPostSchema(BaseModel):
    text_content: str
    author_address: str
    source_type: str
    source_specific_id: str
    published_at: Optional[str] = None
    external_link: Optional[str] = None
    image_url: Optional[str] = None
    language: Optional[str] = "un"
    metadata_: Optional[Dict[str, Any]] = Field(default_factory=dict)

@router.post("/post", status_code=status.HTTP_201_CREATED)
async def ingest_post(request: Request, post_data: IngestPostSchema, db: AsyncSession = Depends(get_db), api_key: str = Depends(verify_ingest_key)):
    try:
        from services.ingest_service import IngestService
        brain = getattr(request.app.state, "brain", None)
        return await IngestService.process_post(db, brain, post_data)
    except Exception as e:
        logger.error(f"Error ingesting post: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/nostr", status_code=status.HTTP_201_CREATED)
async def ingest_raw_nostr(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        raw_json = await request.json()
        from services.ingest_service import IngestService
        brain = getattr(request.app.state, "brain", None)
        return await IngestService.process_nostr_event(db, brain, raw_json)
    except Exception as e:
        logger.error(f"Error ingesting raw nostr: {e}")
        raise HTTPException(status_code=500, detail=str(e))
