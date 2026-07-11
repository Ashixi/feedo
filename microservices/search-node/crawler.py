import asyncio
import json
import os
import time
import random
import httpx
import websockets
from vector_service import VectorBrain
import grpc
try:
    import shared_proto.feedo_pb2 as feedo_pb2
    import shared_proto.feedo_pb2_grpc as feedo_pb2_grpc
except ImportError:
    pass

class SearchCrawler:
    def __init__(self, vector_brain: VectorBrain, adapters: list = None, consensus_url: str = "localhost:50051", http_client: httpx.AsyncClient = None):
        self.vector_brain = vector_brain
        self.adapters = adapters
        self.consensus_url = consensus_url
        self.http_client = http_client

        gateways_env = os.getenv("GATEWAYS", "")
        if gateways_env:
            self.gateways = [g.strip().replace("http://", "").replace("https://", "") for g in gateways_env.split(",") if g.strip()]
        else:
            self.gateways = [os.getenv("STORAGE_NODE_URL", "127.0.0.1:8040").replace("http://", "").replace("https://", "")]

    async def verify_domain_rights(self, did: str, file_hash: str) -> bool:
        """Calls consensus-node via gRPC to verify rights and reputation"""
        try:
            channel = grpc.aio.insecure_channel(self.consensus_url)
            stub = feedo_pb2_grpc.ConsensusServiceStub(channel)
            req = feedo_pb2.VerifyUploadRequest(user_did=did, file_hash=file_hash)
            resp = await stub.VerifyUploadRights(req)
            return resp.is_allowed
        except Exception as e:
            print(f"⚠️ Consensus verification failed for {file_hash}: {e}")
            return False

    async def _forward_vector_to_peer(self, target_url: str, event: dict, vector: list[float]) -> bool:
        """Forward a single vector to a remote search node via /p2p/index_vector."""
        if not self.http_client:
            return False
        try:
            payload = {
                "post_id": event["post_id"],
                "hash_id": event["hash_id"],
                "vector": vector,
                "text": event.get("text", ""),
                "source_type": event.get("source_type", "pubsub"),
                "item_type": event.get("item_type", "text"),
                "author": event.get("author", ""),
                "metadata": event.get("metadata", ""),
            }
            url = f"{target_url}/p2p/index_vector"
            resp = await self.http_client.post(url, json=payload, timeout=5.0)
            if resp.status_code == 200:
                print(f"📤 Routed vector {event['hash_id']} to {target_url}")
                return True
            else:
                print(f"⚠️ Forward to {target_url} returned {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            print(f"⚠️ Failed to forward vector {event['hash_id']} to {target_url}: {e}")
            return False

    async def _flush_batch(self, events: list[dict]):
        """Process a batch of events with semantic sharding write routing."""
        if not events:
            return

        texts = [e["text"] for e in events]
        batch_embeddings = await self.vector_brain.get_embeddings_batch_async(texts)

        for event, chunk_embeddings in zip(events, batch_embeddings):
            try:
                # Use the first (and usually only) chunk embedding
                vector = chunk_embeddings[0] if chunk_embeddings else [0.0] * 384

                # Phase 1.5: Semantic Sharding — write routing
                if self.vector_brain.is_my_shard(vector):
                    # Belongs to this shard — index locally
                    self.vector_brain.add_vector_by_emb(
                        post_id=event["post_id"],
                        hash_id=event["hash_id"],
                        vector=vector,
                        source_type=event.get("source_type", "pubsub"),
                        item_type=event.get("item_type", "text"),
                        author=event.get("author", ""),
                        text=event["text"],
                        metadata=event.get("metadata", ""),
                    )
                else:
                    # Does not belong to this shard — route to the correct node
                    target_url = self.vector_brain.route_vector_to_node(vector)
                    if target_url:
                        forwarded = await self._forward_vector_to_peer(target_url, event, vector)
                        if not forwarded:
                            # Fallback: index locally if forwarding fails
                            self.vector_brain.add_vector_by_emb(
                                post_id=event["post_id"],
                                hash_id=event["hash_id"],
                                vector=vector,
                                source_type=event.get("source_type", "pubsub"),
                                item_type=event.get("item_type", "text"),
                                author=event.get("author", ""),
                                text=event["text"],
                                metadata=event.get("metadata", ""),
                            )
                    else:
                        # No routing target available — fallback to local
                        self.vector_brain.add_vector_by_emb(
                            post_id=event["post_id"],
                            hash_id=event["hash_id"],
                            vector=vector,
                            source_type=event.get("source_type", "pubsub"),
                            item_type=event.get("item_type", "text"),
                            author=event.get("author", ""),
                            text=event["text"],
                            metadata=event.get("metadata", ""),
                        )
            except Exception as e:
                print(f"⚠️ Error processing batch vector for {event.get('hash_id')}: {e}")

    async def crawl_loop(self):
        print(f"🚀 Starting Event-Driven Crawler with batch processing. Configured gateways: {self.gateways}")
        
        current_gateway_idx = 0
        
        while True:
            gateway = self.gateways[current_gateway_idx]
            ws_url = f"ws://{gateway}/api/v1/pubsub/subscribe/feedo_new_events"
            print(f"🔄 Crawler connecting to {ws_url}...")
            
            try:
                async with websockets.connect(ws_url) as ws:
                    print(f"✅ Connected to PubSub WebSocket on {gateway}!")
                    
                    # Batch buffer: accumulate up to 32 events or 1 second
                    pending_events = []
                    last_flush_time = time.monotonic()
                    
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            
                            hash_id = data.get("hash_id")
                            text = data.get("text")
                            if not hash_id or not text or len(text.strip()) < 5:
                                continue
                                
                            author = data.get("author", "")
                            metadata_dict = data.get("metadata", {})
                            metadata_str = json.dumps(metadata_dict) if metadata_dict else ""
                            
                            print(f"🔎 Got event via PubSub! Buffering: {hash_id}")
                            
                            post_id = random.randint(100000, 999999)
                            pending_events.append({
                                "post_id": post_id,
                                "hash_id": hash_id,
                                "text": text,
                                "source_type": "pubsub",
                                "item_type": "text",
                                "author": author,
                                "metadata": metadata_str
                            })
                            
                            # Flush when buffer is full or 1 second elapsed
                            now = time.monotonic()
                            if len(pending_events) >= 32 or (now - last_flush_time) >= 1.0:
                                await self._flush_batch(pending_events)
                                pending_events = []
                                last_flush_time = now
                                
                        except Exception as e:
                            print(f"⚠️ Error parsing pubsub message: {e}")
                    
                    # Flush remaining events when WebSocket closes
                    if pending_events:
                        await self._flush_batch(pending_events)
                        
            except Exception as e:
                print(f"❌ WebSocket connection lost to {gateway}: {e}")
                
            current_gateway_idx = (current_gateway_idx + 1) % len(self.gateways)
            print("⚠️ Trying next gateway in 3s...")
            await asyncio.sleep(3)

