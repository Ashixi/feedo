import enum
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, Table, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship, foreign  
from sqlalchemy import JSON
from database import Base


def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

class SourceTypeEnum(enum.Enum):
    TELEGRAM = "telegram"
    REDDIT = "reddit"
    RSS = "rss"
    NATIVE = "native" 

class ContentType(enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"

class ApiKeyRole(enum.Enum):
    ANONYMOUS = "anonymous"
    DEVELOPER = "developer"
    PROVIDER = "provider"

user_subscriptions = Table(
    "user_subscriptions",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("source_id", Integer, ForeignKey("sources.id"), primary_key=True)
)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, unique=True, index=True, nullable=False, default=lambda: f"user_{uuid.uuid4().hex[:8]}")
    username = Column(String, unique=True, index=True) 
    wallet_address = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, nullable=True)
    
    bio = Column(Text, nullable=True)
    avatar_media_hash = Column(String, nullable=True)
    preferred_languages = Column(JSON, default=[])    
    preferred_tags = Column(JSON, default=[])
    api_url = Column(String, nullable=True)
    user_vector = Column(JSON, nullable=True) 
    last_vector_updated_at = Column(DateTime(timezone=True), default=_naive_utc_now)
    indexed_posts_count = Column(Integer, default=0)

    
    is_admin = Column(Boolean, default=False)
    
    subscriptions = relationship("Source", secondary=user_subscriptions, back_populates="subscribers")
    posts = relationship("Post", back_populates="author", primaryjoin="User.wallet_address == foreign(Post.author_address)")



class Delegation(Base):
    __tablename__ = "delegations"
    id = Column(Integer, primary_key=True)
    delegator_wallet = Column(String, index=True, nullable=False)
    delegatee_wallet = Column(String, index=True, nullable=False)
    permissions = Column(JSON, default=[]) 
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    signature = Column(String, nullable=False) 



class Source(Base):
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String, unique=True, index=True)
    source_type = Column(Enum(SourceTypeEnum), default=SourceTypeEnum.RSS)
    name = Column(String)
    language = Column(String(10), nullable=True, index=True)

    posts = relationship("Post", back_populates="source")
    subscribers = relationship("User", secondary=user_subscriptions, back_populates="subscriptions")

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True) 
    
    source_type = Column(String, index=True, nullable=False, default="native") 
    source_specific_id = Column(String, index=True, nullable=True) 
    metadata_ = Column(JSON, default={}) 
    
    content_type = Column(Enum(ContentType), default=ContentType.TEXT)
    author_address = Column(String, nullable=True, index=True)
    
    hash_id = Column(String, unique=True, index=True, nullable=True)     
    content_blob_hash = Column(String, index=True, nullable=True)        
    
    prev_post_hash = Column(String, index=True, nullable=True, default="")
    sequence_number = Column(Integer, default=0)

    signature = Column(String, nullable=True)
    is_finalized = Column(Boolean, default=False)
    
    is_verified = Column(Boolean, default=True) 
    is_repost = Column(Boolean, default=False)  

    original_author_name = Column(String, nullable=True)
    
    title = Column(String, nullable=True)
    
    text_content = Column(Text) 
    content_size = Column(Integer, default=0) 
    is_full_content_loaded = Column(Boolean, default=True) 
    
    external_link = Column(String, nullable=True) 
    published_at = Column(DateTime, default=_naive_utc_now)
    source_internal_id = Column(String, nullable=True) 
    language = Column(String(10), default="uk")

    parent_post_id = Column(Integer, ForeignKey("posts.id"), nullable=True, index=True)
    
    main_post = relationship("Post", remote_side=[id], back_populates="duplicates")
    
    duplicates = relationship("Post", back_populates="main_post")

    source = relationship("Source", back_populates="posts")
    author = relationship("User", back_populates="posts", primaryjoin="foreign(Post.author_address) == User.wallet_address")
    
    __table_args__ = (
        UniqueConstraint('source_type', 'source_specific_id', name='_source_type_id_uc'),
    )








class UserKey(Base):
    __tablename__ = "user_keys"
    id = Column(Integer, primary_key=True)
    wallet_address = Column(String, nullable=False, index=True, unique=True)
    pub_enc_key = Column(String, nullable=False)
    sig_of_pub_enc_key = Column(String, nullable=False)
    published_at = Column(DateTime, default=_naive_utc_now)
    expires_at = Column(DateTime, nullable=True)





class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    hashed_key = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(Enum(ApiKeyRole), nullable=False, default=ApiKeyRole.DEVELOPER)
    owner_address = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=_naive_utc_now)
    expires_at = Column(DateTime, nullable=True)
    revoked = Column(Boolean, default=False)
    rate_limit_bucket = Column(JSON, nullable=True, default={})


class Edge(Base):
    __tablename__ = "edges"
    id = Column(Integer, primary_key=True)
    source_hash = Column(String, nullable=False, index=True)
    target_hash = Column(String, nullable=False, index=True)
    edge_type = Column(String, nullable=False, index=True) 
    author_address = Column(String, nullable=False, index=True)
    signature = Column(String, nullable=False)
    created_at = Column(DateTime, default=_naive_utc_now)


class CreditBalance(Base):
    __tablename__ = "credit_balances"
    id = Column(Integer, primary_key=True)
    wallet_address = Column(String, nullable=False, index=True, unique=True)
    balance = Column(Integer, default=0) 
    updated_at = Column(DateTime, default=_naive_utc_now, onupdate=_naive_utc_now)


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    id = Column(Integer, primary_key=True)
    tx_hash = Column(String, nullable=False, index=True, unique=True)
    wallet_address = Column(String, nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    signature = Column(String, nullable=False)
    created_at = Column(DateTime, default=_naive_utc_now)
