import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import AsyncSessionLocal
from sqlalchemy.future import select
from models import Post
import lancedb
import pyarrow as pa
import time

async def migrate_lancedb():
    db_path = "./lancedb_data"
    db = lancedb.connect(db_path)
    table_name = "post_vectors"
    
    if table_name not in db.table_names():
        print("Table does not exist. Nothing to migrate.")
        return
        
    old_table = db.open_table(table_name)
    
    if "hash_id" in old_table.schema.names:
        print("Table already has hash_id. No migration needed.")
        return
        
    print("Fetching all existing vectors...")
    try:
        all_data = old_table.search().limit(1000000).to_list()
    except Exception as e:
        print(f"Could not read old table: {e}")
        return
    
    print(f"Loaded {len(all_data)} vectors. Querying Postgres for hash_ids...")
    new_data = []
    
    async with AsyncSessionLocal() as session:
        for row in all_data:
            post_id = row.get("post_id")
            if not post_id:
                continue
                
            stmt = select(Post.hash_id).where(Post.id == post_id)
            hash_id = (await session.execute(stmt)).scalar_one_or_none()
            
            if hash_id:
                new_data.append({
                    "post_id": post_id,
                    "hash_id": hash_id,
                    "vector": row["vector"],
                    "timestamp": row.get("timestamp", time.time()),
                    "source_type": row.get("source_type", "native"),
                    "language": row.get("language", ""),
                    "geo": row.get("geo", "")
                })
                
    print(f"Mapped {len(new_data)} vectors to hash_ids.")
    print("Dropping old table and creating new one...")
    db.drop_table(table_name)
    
    schema = pa.schema([
        pa.field("post_id", pa.int32()),
        pa.field("hash_id", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 1024)),
        pa.field("timestamp", pa.float64()),
        pa.field("source_type", pa.string()),
        pa.field("language", pa.string()),
        pa.field("geo", pa.string())
    ])
    
    new_table = db.create_table(table_name, schema=schema)
    if new_data:
        new_table.add(new_data)
        
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate_lancedb())
