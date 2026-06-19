import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator
import uuid

import hashlib
import httpx

from .base import BaseSource
from .text_utils import clean_plain_text, clean_html_text, chunk_long_text

logger = logging.getLogger("paragraph_source")

ARWEAVE_GRAPHQL_URL = "https://arweave.net/graphql"
ARWEAVE_GATEWAY = "https://arweave.net/"

class ParagraphSource(BaseSource):
    source_type = "paragraph"
    
    def __init__(self):
        super().__init__()
        self.seen_txs = set()
        self.last_min_created_at = None
        self.last_arweave_cursor = None

    async def fetch_new(self, since: datetime | None) -> list[dict]:
        return []

    async def fetch_new_batches(self, since: datetime | None, node_index: int = 0, total_nodes: int = 1, db=None, override_since_ts: int = None, override_until_ts: int = None, arweave_cursor: str = None):
        # Determine time window
        since_ts = override_since_ts if override_since_ts else int(datetime.utcnow().timestamp()) - (6 * 3600)
        
        # We query the latest transactions tagged with App-Name: MirrorXYZ or Paragraph
        # In a real heavy backfill we would use GraphQL cursors, but here we just fetch top 100 for live monitor.
        
        query = """
        query($cursor: String) {
          transactions(
            tags: [
              { name: "App-Name", values: ["MirrorXYZ", "Paragraph"] }
            ]
            first: 100
            sort: HEIGHT_DESC
            after: $cursor
          ) {
            edges {
              cursor
              node {
                id
                block {
                  timestamp
                }
                tags {
                  name
                  value
                }
              }
            }
          }
        }
        """
        
        # We will use transaction ID hash to shard the heavy Arweave gateway requests across nodes
        # so all nodes participate in fetching without duplicating work.
        
        variables = {"cursor": arweave_cursor} if arweave_cursor else {}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(ARWEAVE_GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=20.0)
                data = resp.json()
            except Exception as e:
                logger.error(f"Error querying Arweave GraphQL: {e}")
                return
                
        edges = data.get("data", {}).get("transactions", {}).get("edges", [])
        if not edges:
            logger.info("ParagraphSource: No new transactions found.")
            return
            
        last_cursor = edges[-1].get("cursor") if edges else None
        batch_timestamps = []
        batch_posts = []
        
        async with httpx.AsyncClient() as client:
            for edge in edges:
                node = edge.get("node", {})
                tx_id = node.get("id")
                
                # Extract timestamp from block if available, else from tags
                block = node.get("block")
                ts = block.get("timestamp") if block else None
                
                if not ts:
                    ts = int(datetime.utcnow().timestamp())
                    
                batch_timestamps.append(ts)
                
                if tx_id in self.seen_txs:
                    continue
                self.seen_txs.add(tx_id)
                
                # Parse tags
                tags = node.get("tags", [])
                tag_dict = {t["name"]: t["value"] for t in tags}
                
                # Shard the heavy downloading process across nodes
                if total_nodes > 1:
                    tx_hash_int = int(hashlib.md5(tx_id.encode()).hexdigest(), 16)
                    if tx_hash_int % total_nodes != node_index:
                        continue
                
                # Check timeframe
                if override_since_ts and ts < override_since_ts:
                    continue
                if override_until_ts and ts > override_until_ts:
                    continue
                    
                # Fetch JSON data from gateway
                try:
                    res = await client.get(f"{ARWEAVE_GATEWAY}{tx_id}", timeout=10.0)
                    if res.status_code != 200:
                        if res.status_code == 429:
                            logger.warning(f"Rate limited by Arweave gateway! Sleeping 5s...")
                            await asyncio.sleep(5)
                        else:
                            logger.debug(f"Gateway returned {res.status_code} for {tx_id}")
                        continue
                    
                    article_data = res.json()
                except Exception as e:
                    logger.debug(f"Failed to fetch article {tx_id}: {e}")
                    continue
                    
                # Anti-rate-limit delay
                await asyncio.sleep(0.5)
                    
                content = article_data.get("content", {})
                title = content.get("title", tag_dict.get("Title", "Untitled"))
                body = content.get("body", "")
                
                if not body and "text" in article_data:
                    body = article_data["text"]
                if not body and isinstance(article_data, dict):
                    body = " ".join([str(v) for v in article_data.values() if isinstance(v, str)])
                    
                if not body.strip():
                    continue
                    
                # Clean and chunk the text
                cleaned_text = clean_html_text(body)
                chunks = chunk_long_text(cleaned_text, chunk_size=512, overlap=50)
                
                pub_date = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
                author = tag_dict.get("Contributor", "UnknownAuthor")
                
                for i, chunk in enumerate(chunks):
                    if not chunk.strip():
                        continue
                        
                    batch_posts.append({
                        "source_specific_id": f"arweave_{tx_id}_chunk_{i}",
                        "text_content": chunk,
                        "author_address": author,
                        "original_author_name": f"Mirror:{author[:8]}",
                        "signature": tx_id,
                        "hash_id": f"{tx_id}_c{i}", 
                        "published_at": pub_date,
                        "relay_url": f"https://mirror.xyz/{author}/{tx_id}",
                        "item_type": "article_chunk",
                        "metadata_": {
                            "tx_id": tx_id,
                            "chunk_index": i,
                            "total_chunks": len(chunks),
                            "title": title
                        }
                    })
                    
        if batch_timestamps:
            batch_timestamps.sort()
            median_ts = batch_timestamps[len(batch_timestamps) // 2]
            self.last_min_created_at = median_ts
        else:
            self.last_min_created_at = int(datetime.utcnow().timestamp())
            
        self.last_arweave_cursor = last_cursor
        
        if batch_posts:
            yield batch_posts
