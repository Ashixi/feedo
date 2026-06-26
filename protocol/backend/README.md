# Feedo Backend (FastAPI + VectorBrain)

This is the core API server for the Feedo Protocol. It handles user identities, feed curation, semantic search, and the AI vector engine.

## Key Technologies

- **FastAPI**: The web framework for high-performance async REST endpoints.
- **LanceDB**: A lightweight, fast vector database used to store and query the semantic embeddings of posts and users.
- **SentenceTransformers**: Powers the VectorBrain. It uses clip-ViT-B-32 for image vectorization and multilingual-e5-small for text vectorization.
- **PostgreSQL**: Used for basic metadata, relationships, and tracking (via SQLAlchemy). Note: Original post content is NOT stored here.

## Core API Routes

- POST /api/v1/ingest/post: The secure endpoint where worker scripts (like the Nostr Bridge) submit new content. Requires X-Ingest-Key header.
- GET /api/v1/feed/personal: Serves the personalized, algorithmic Anti-Bubble feed based on the user's local interaction vector.
- GET /api/v1/semantic/search: Performs a semantic vector search across the entire database.

## Local Setup

### 1. Requirements
- Python 3.10+
- PostgreSQL server (can be run via docker-compose from the project root)

### 2. Environment Variables
Create a .env file in /protocol/backend:
\\\ash
DATABASE_URL="postgresql+asyncpg://user:password@localhost/feedo"
INGEST_API_KEY="your_secure_ingest_key_here"
RUST_CORE_URL="http://localhost:8050" # Pointer to the P2P Node
\\\

### 3. Installation
\\\ash
python -m venv venv
# Windows: venv\Scripts\activate, Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
\\\

### 4. Running the Server
\\\ash
uvicorn main:app --host 0.0.0.0 --port 8040 --reload
\\\

You can view the interactive API documentation at http://localhost:8040/docs.
