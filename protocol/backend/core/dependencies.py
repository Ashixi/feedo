from database import AsyncSessionLocal
from fastapi import Request

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

def get_brain(request: Request):
    return getattr(request.app.state, 'brain', None)

def get_p2p(request: Request):
    return getattr(request.app.state, 'p2p', None)

