from sqlalchemy import select, Column, Integer, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Post(Base):
    __tablename__ = 'test'
    id = Column(Integer, primary_key=True)
    metadata_ = Column(JSON)

try:
    print(Post.metadata_['language'].astext)
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
