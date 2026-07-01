import asyncio
from services.vector_service import VectorService
import lancedb
import pandas as pd

async def main():
    try:
        vs = VectorService()
        table = vs.table
        df = table.to_pandas()
        print(f"Vectors in LanceDB: {len(df)}")
        print(df['item_type'].value_counts())
    except Exception as e:
        print(e)

if __name__ == "__main__":
    asyncio.run(main())
