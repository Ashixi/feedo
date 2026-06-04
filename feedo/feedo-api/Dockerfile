FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc libssl-dev && rm -rf /var/lib/apt/lists/*
COPY . .
RUN pip install --no-cache-dir fastapi uvicorn sqlalchemy asyncpg lancedb pyarrow sentence-transformers feedparser httpx cryptography ecdsa requests