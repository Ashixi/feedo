import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, create_engine

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
try:
    from database import Base, engine as async_engine
except Exception:
    # fallback: try relative import
    from feedo_api.database import Base, engine as async_engine


def run_migrations_offline():
    """Run migrations in 'offline' mode.
    We'll simply create tables from metadata using a sync engine.
    """
    url = os.getenv('DATABASE_URL') or config.get_main_option('sqlalchemy.url')
    if url is None:
        raise RuntimeError('DATABASE_URL not set')

    # convert async URL to sync if necessary
    sync_url = url.replace('+aiosqlite', '').replace('+asyncpg', '')
    engine = create_engine(sync_url)
    Base.metadata.create_all(bind=engine)


def run_migrations_online():
    """Run migrations in 'online' mode."""
    # If AsyncEngine provided in database module, use its sync_engine
    sync_engine = getattr(async_engine, 'sync_engine', None)
    if sync_engine is None:
        url = os.getenv('DATABASE_URL') or config.get_main_option('sqlalchemy.url')
        sync_url = url.replace('+aiosqlite', '').replace('+asyncpg', '')
        sync_engine = create_engine(sync_url)

    # create tables from metadata
    Base.metadata.create_all(bind=sync_engine)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
