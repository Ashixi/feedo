import asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select

from database import Base
from social_events import event_store
from models import Notification

@pytest.mark.asyncio
async def test_add_notification_creates_record(tmp_path):
    db_file = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    AsyncLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncLocal() as session:
        item = await event_store.add_notification(
            session,
            "0xabc",
            "like",
            "Test Like",
            "Someone liked your post",
            source_wallet="0xdef",
            post_title="Hello",
            meta={"post_id": 1},
        )
        assert isinstance(item, dict)
        assert item.get("type") == "like"
        assert item.get("source_wallet") == "0xdef"

        # verify persisted in DB
        res = (await session.execute(select(Notification).where(Notification.id == item["id"]))).scalar_one_or_none()
        assert res is not None
        assert res.type == "like"
        assert res.recipient_wallet == "0xabc"
