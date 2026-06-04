
import argparse
import asyncio
import sys

from database import engine, Base, ensure_postgres_database_exists


async def rebuild_db(confirm: bool) -> None:
    if not confirm:
        print("Refusing to run without --yes. This would DROP ALL TABLES.")
        return

    await ensure_postgres_database_exists()

    print("Dropping all tables...")
    async with engine.begin() as conn:
        try:
            await conn.run_sync(Base.metadata.drop_all)
        except Exception as e:
            print(f"Error while dropping tables: {e}")
            raise

    print("Creating tables...")
    async with engine.begin() as conn:
        try:
            await conn.run_sync(Base.metadata.create_all)
        except Exception as e:
            print(f"Error while creating tables: {e}")
            raise

    print("Database schema rebuilt successfully.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Recreate DB schema from SQLAlchemy models")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive action")
    args = parser.parse_args(argv)

    try:
        asyncio.run(rebuild_db(args.yes))
    except Exception as e:
        print(f"Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
