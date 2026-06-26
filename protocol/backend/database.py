import os
from dotenv import load_dotenv
import asyncpg
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

# Завантажуємо змінні з .env файлу, якщо він існує (для локальної розробки)
# Docker Compose передає змінні напряму в оточення, тому там цей метод просто нічого не зробить
load_dotenv()

# Отримуємо URL бази даних
# Якщо ми в Docker, підтягнеться postgresql+asyncpg://...
# Якщо запускаємо локально без .env, відкататься на sqlite
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "sqlite+aiosqlite:///./db_data/feedo.db"
)

# Налаштування двигуна залежно від типу БД
if DATABASE_URL.startswith("sqlite"):
    # Створюємо папку для SQLite, якщо її немає
    os.makedirs("./db_data", exist_ok=True)
    # Для SQLite додаємо таймаут, щоб уникнути "database is locked"
    engine = create_async_engine(
        DATABASE_URL, 
        echo=False, 
        connect_args={"timeout": 20.0}
    )
else:
    # Для PostgreSQL використовуємо стандартні налаштування
    # NullPool avoids reusing asyncpg connections across different event loops
    # (the API loop and the background monitor thread both use this engine).
    engine = create_async_engine(
        DATABASE_URL, 
        echo=False,
        pool_pre_ping=True,
        poolclass=NullPool
    )

AsyncSessionLocal = sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

Base = declarative_base()


async def ensure_postgres_database_exists() -> None:
    """Create the target PostgreSQL database if it is missing.

    This is a no-op for SQLite and for non-PostgreSQL URLs.
    """
    if not DATABASE_URL.startswith(("postgresql", "postgres")):
        return

    url = make_url(DATABASE_URL)
    database_name = url.database
    if not database_name:
        return

    maintenance_database = url.set(database="postgres")
    connection = await asyncpg.connect(
        user=maintenance_database.username,
        password=maintenance_database.password,
        database=maintenance_database.database or "postgres",
        host=maintenance_database.host or "localhost",
        port=maintenance_database.port or 5432,
    )

    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            database_name,
        )
        if not exists:
            safe_database_name = database_name.replace('"', '""')
            await connection.execute(f'CREATE DATABASE "{safe_database_name}"')
    finally:
        await connection.close()

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()