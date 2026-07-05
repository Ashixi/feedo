import asyncio
import json
import os
import websockets
from vector_service import VectorBrain
import grpc
try:
    import shared_proto.feedo_pb2 as feedo_pb2
    import shared_proto.feedo_pb2_grpc as feedo_pb2_grpc
except ImportError:
    pass

class SearchCrawler:
    def __init__(self, vector_brain: VectorBrain, adapters: list = None, consensus_url: str = "localhost:50051"):
        self.vector_brain = vector_brain
        self.adapters = adapters
        self.consensus_url = consensus_url
        
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

    async def crawl_loop(self):
        print(f"🚀 Starting Event-Driven Crawler. Configured gateways: {self.gateways}")
        
        current_gateway_idx = 0
        
        while True:
            gateway = self.gateways[current_gateway_idx]
            ws_url = f"ws://{gateway}/api/v1/pubsub/subscribe/feedo_new_events"
            print(f"🔄 Crawler connecting to {ws_url}...")
            
            try:
                async with websockets.connect(ws_url) as ws:
                    print(f"✅ Connected to PubSub WebSocket on {gateway}!")
                    async for message in ws:
                        try:
                            # It's a JSON payload containing the event data
                            data = json.loads(message)
                            
                            hash_id = data.get("hash_id")
                            text = data.get("text")
                            if not hash_id or not text or len(text.strip()) < 5:
                                continue
                                
                            author = data.get("author", "")
                            metadata_dict = data.get("metadata", {})
                            metadata_str = json.dumps(metadata_dict) if metadata_dict else ""
                            
                            print(f"🔎 Got event via PubSub! Vectorizing: {hash_id}")
                            
                            import random
                            post_id = random.randint(100000, 999999)
                            await self.vector_brain.add_vector_async(
                                post_id=post_id,
                                hash_id=hash_id,
                                text=text,
                                source_type="pubsub",
                                item_type="text",
                                author=author,
                                metadata=metadata_str
                            )
                        except Exception as e:
                            print(f"⚠️ Error parsing pubsub message: {e}")
            except Exception as e:
                print(f"❌ WebSocket connection lost to {gateway}: {e}")
                
            current_gateway_idx = (current_gateway_idx + 1) % len(self.gateways)
            print("⚠️ Trying next gateway in 3s...")
            await asyncio.sleep(3)

