from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from database import Base
import datetime

class Identity(Base):
    __tablename__ = "identities"

    id = Column(Integer, primary_key=True, index=True)
    did = Column(String, unique=True, index=True, nullable=False)
    public_key = Column(String, nullable=False)
    reputation = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class NetworkNode(Base):
    __tablename__ = "network_nodes"

    id = Column(Integer, primary_key=True, index=True)
    peer_id = Column(String, unique=True, index=True, nullable=False)
    is_supernode = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String, default="active")

class ConsensusLog(Base):
    __tablename__ = "consensus_logs"

    id = Column(Integer, primary_key=True, index=True)
    round_id = Column(Integer, index=True)
    block_hash = Column(String, nullable=False)
    status = Column(String, nullable=False)  # e.g., "committed", "proposed"
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
