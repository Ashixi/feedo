import asyncio
from backend.indexer import fetch_and_index

async def main():
    try:
        await fetch_and_index()
        print("Success")
    except Exception as e:
        print(f"Failed with exception: {e}")

if __name__ == "__main__":
    asyncio.run(main())
