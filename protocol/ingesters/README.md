# Feedo Ingesters

Ingesters are independent worker microservices responsible for pulling content from external networks (like Nostr, RSS feeds, Farcaster, etc.) and submitting it to the Feedo Backend.

## Architecture

Ingesters are entirely stateless and isolated from the main PostgreSQL or LanceDB databases. They do **not** have direct database access.

Instead, they fetch data, perform initial cleanup, and send an HTTP `POST` request to the Backend's `/api/v1/ingest/post` endpoint.

## Nostr Bridge (`/nostr-bridge`)

The primary ingester currently is the **Nostr Bridge**. 

### How it Works
1. **Infinite Loop**: It runs an infinite `asyncio` loop, connecting to multiple global Nostr WebSocket relays.
2. **Quality Control (Pre-filtering)**: To save bandwidth and backend processing power, it drops low-quality events immediately. For example, it detects if an event is a "reply" (`is_reply = True`) and drops it, ensuring the algorithmic feed only receives root-level posts.
3. **Stateless Forwarding**: It extracts the bare minimum text and the `relay_url` and sends it to the Backend. It does NOT download media files to disk.

### Running Locally
```bash
cd nostr-bridge
pip install -r requirements.txt
export INGEST_URL="http://127.0.0.1:8040/api/v1/ingest/post"
export INGEST_API_KEY="your_secure_key"
python nostr_source.py
```

## Building a Custom Ingester

You can easily build a new ingester for any platform (e.g., Reddit, RSS, Twitter). 
All you need is a script in any language that makes a POST request to the backend:

```json
POST /api/v1/ingest/post
Headers: { "X-Ingest-Key": "..." }

{
    "text_content": "The raw text of the post",
    "author_address": "author_id_or_pubkey",
    "source_type": "rss",
    "source_specific_id": "unique_id_from_source",
    "external_link": "https://url-to-original-post",
    "image_url": "https://url-to-image.jpg"
}
```
