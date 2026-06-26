import asyncio
import secrets
import hashlib
import sys
import os

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import AsyncSessionLocal
from models import ApiKey, ApiKeyRole

async def main():
    if len(sys.argv) < 3:
        print("Usage: python create_api_key.py <name> <role: anonymous|developer|provider> [owner_address]")
        sys.exit(1)
        
    name = sys.argv[1]
    role_str = sys.argv[2]
    owner = sys.argv[3] if len(sys.argv) > 3 else None
    
    try:
        role_enum = ApiKeyRole(role_str.lower())
    except ValueError:
        print("Invalid role. Must be one of: anonymous, developer, provider")
        sys.exit(1)
        
    raw_key = secrets.token_urlsafe(32)
    hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
    
    async with AsyncSessionLocal() as db:
        new_key = ApiKey(
            hashed_key=hashed_key,
            name=name,
            role=role_enum,
            owner_address=owner,
            rate_limit_bucket={}
        )
        db.add(new_key)
        await db.commit()
        await db.refresh(new_key)
        
        print("API Key Created Successfully!")
        print(f"ID: {new_key.id}")
        print(f"Name: {new_key.name}")
        print(f"Role: {new_key.role.value}")
        print(f"Raw Key: {raw_key}")
        print("--------------------------------------------------")
        print("SAVE THIS RAW KEY! It is only shown once and cannot be recovered.")

if __name__ == "__main__":
    asyncio.run(main())
