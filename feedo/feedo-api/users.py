# feedo-api/routers/users.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timezone
from pydantic import BaseModel

from database import get_db
from models import User, Post
from auth import validate_zero_trust_request
from models import UserKey
from sqlalchemy import or_, and_, func
from pydantic import BaseModel
from typing import List

router = APIRouter(prefix="/users", tags=["Users"])


def _normalize_wallet(wallet_address: str) -> str:
    cleaned = wallet_address.strip().lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    if len(cleaned) == 130 and cleaned.startswith("04"):
        cleaned = cleaned[2:]
    return cleaned


def _user_display_label(user: User | None, fallback_wallet: str | None = None) -> str:
    if user:
        for value in (user.display_name, user.username, user.public_id):
            if isinstance(value, str) and value.strip():
                return value.strip()
    if fallback_wallet:
        return fallback_wallet
    return "Unknown Node"


async def _load_user_by_wallet(db: AsyncSession, wallet_address: str) -> User | None:
    normalized = _normalize_wallet(wallet_address)
    stmt = select(User).where(func.lower(User.wallet_address).in_((normalized, f"0x{normalized}")))
    return (await db.execute(stmt)).scalar_one_or_none()







class SearchResponseItem(BaseModel):
    public_id: str
    username: str
    wallet_address: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    pub_enc_key: str | None = None


@router.get("/search", response_model=List[SearchResponseItem])
async def search_users(q: str, requester_wallet: str | None = None, db: AsyncSession = Depends(get_db)):
    """Search by public_id, username or display name."""
    term = q.lstrip("@ ").strip()
    if not term:
        return []

    normalized_wallet = _normalize_wallet(term)

    if term.startswith("user_"):
        stmt = select(User).where(User.public_id == term)
    else:
        pattern = f"%{term}%"
        stmt = select(User).where(
            or_(
                User.public_id == term,
                func.lower(User.wallet_address).in_((normalized_wallet, f"0x{normalized_wallet}")),
                User.username.ilike(pattern),
                User.display_name.ilike(pattern),
            )
        )

    res = await db.execute(stmt)
    candidates = res.scalars().all()

    # filter out blocked users if requester provided
    filtered = []
    for u in candidates:


        # find pub_enc_key if available
        stmt_k = select(UserKey).where(UserKey.wallet_address == u.wallet_address)
        key = (await db.execute(stmt_k)).scalar_one_or_none()
        filtered.append({
            "public_id": u.public_id,
            "username": u.username or u.public_id or _user_display_label(u, u.wallet_address),
            "wallet_address": u.wallet_address,
            "display_name": u.display_name or u.username or u.public_id,
            "label": _user_display_label(u, u.wallet_address),
            "avatar_url": f"/p2p-media/{u.avatar_media_hash}" if u.avatar_media_hash else None,
            "bio": u.bio,
            "pub_enc_key": key.pub_enc_key if key else None
        })

    return filtered


class SearchPostItem(BaseModel):
    id: int
    title: str | None = None
    text: str
    published_at: datetime
    author_address: str | None = None
    display_author: str
    source_type: str
    metadata: dict | None = None
    avatar_url: str | None = None
    sequence_number: int = 0


@router.get("/search/posts", response_model=List[SearchPostItem])
async def search_posts(q: str, db: AsyncSession = Depends(get_db)):
    term = q.lstrip("@ ").strip()
    if not term:
        return []

    pattern = f"%{term}%"
    stmt = (
        select(Post, User)
        .outerjoin(User, Post.author_address == User.wallet_address)
        .where(
            or_(
                Post.title.ilike(pattern),
                Post.text_content.ilike(pattern),
                Post.hash_id.ilike(pattern),
                User.username.ilike(pattern),
                User.display_name.ilike(pattern),
                User.public_id.ilike(pattern),
            )
        )
        .order_by(Post.published_at.desc())
        .limit(50)
    )
    rows = (await db.execute(stmt)).all()

    results = []
    for post, author in rows:
        display_author = _user_display_label(author, post.author_address)
        results.append(
            {
                "id": post.id,
                "title": post.title,
                "text": post.text_content or "",
                "published_at": post.published_at,
                "author_address": post.author_address,
                "display_author": display_author,
                "source_type": post.source_type,
                "metadata": post.metadata_ or {},
                "avatar_url": f"/p2p-media/{author.avatar_media_hash}" if author and author.avatar_media_hash else None,
                "sequence_number": post.sequence_number,
            }
        )

    return results





@router.get("/{wallet_address}/pub_enc_key")
async def get_user_pub_enc_key(wallet_address: str, db: AsyncSession = Depends(get_db)):
    """Return the last published public encryption key for a user, if any."""
    stmt = select(UserKey).where(UserKey.wallet_address == wallet_address)
    key = (await db.execute(stmt)).scalar_one_or_none()
    if not key:
        return {"pub_enc_key": None}
    return {"pub_enc_key": key.pub_enc_key}





class DeleteAccountRequest(BaseModel):
    wallet_address: str
    timestamp: int
    signature: str


@router.post("/delete")
async def delete_account(req: DeleteAccountRequest, db: AsyncSession = Depends(get_db)):
    # 1. Zero Trust signature validation
    validate_zero_trust_request(
        req.wallet_address,
        req.timestamp,
        {},
        req.signature
    )
    
    wallet = _normalize_wallet(req.wallet_address)
    
    # Import necessary models and operations locally
    from sqlalchemy import delete, update
    from models import (
        User, Post, UserKey
    )
    
    # 2. Deleting interactions on user's posts or by user
    post_ids_stmt = select(Post.id).where(Post.author_address == wallet)
    post_ids = (await db.execute(post_ids_stmt)).scalars().all()
    
    if post_ids:
        
        # Unlink parent/duplicate post references so we don't violate FK constraints
        await db.execute(
            update(Post)
            .where(Post.parent_post_id.in_(post_ids))
            .values(parent_post_id=None)
        )
        
        # Delete the posts themselves
        await db.execute(delete(Post).where(Post.id.in_(post_ids)))
        
    
    # 8. Delete user's public encryption keys
    await db.execute(delete(UserKey).where(UserKey.wallet_address == wallet))
    
    # 9. Finally, delete the User record
    await db.execute(delete(User).where(User.wallet_address == wallet))
    
    await db.commit()
    
    return {"status": "success", "message": "Акаунт та всі пов'язані дані успішно видалено."}
