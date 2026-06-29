import asyncio
import json
import logging
import websockets
from typing import List

logger = logging.getLogger("spider_service")

class NostrSpider:
    SEARCH_RELAYS = [
        "wss://relay.nostr.band",
        "wss://search.nos.today",
        "wss://nos.lol",
        "wss://relay.primal.net"
    ]

    @staticmethod
    async def search_profiles(query: str, limit: int = 20, timeout_sec: float = 3.0) -> List[dict]:
        """
        Sends a NIP-50 search query for profiles (kind: 0) to global indexer relays.
        Returns a list of raw event dictionaries.
        """
        if not query or len(query.strip()) < 2:
            return []

        req_id = f"search_spider_{id(query)}"
        filter_req = {
            "kinds": [0],
            "search": query,
            "limit": limit
        }
        
        req_msg = json.dumps(["REQ", req_id, filter_req])
        results = []
        seen_pubkeys = set()

        async def fetch_from_relay(relay: str):
            try:
                async with websockets.connect(relay, open_timeout=1.0) as ws:
                    await ws.send(req_msg)
                    
                    start_time = asyncio.get_running_loop().time()
                    while True:
                        elapsed = asyncio.get_running_loop().time() - start_time
                        if elapsed >= timeout_sec:
                            break
                        
                        try:
                            msg_str = await asyncio.wait_for(ws.recv(), timeout=timeout_sec - elapsed)
                            msg = json.loads(msg_str)
                            
                            if msg[0] == "EOSE" and msg[1] == req_id:
                                break
                            
                            if msg[0] == "EVENT" and msg[1] == req_id:
                                ev = msg[2]
                                pubkey = ev.get("pubkey")
                                if pubkey and pubkey not in seen_pubkeys:
                                    seen_pubkeys.add(pubkey)
                                    results.append(ev)
                                    
                        except asyncio.TimeoutError:
                            break
                        except Exception as e:
                            logger.debug(f"Spider parse error from {relay}: {e}")
                            break
                            
                    try:
                        await ws.send(json.dumps(["CLOSE", req_id]))
                    except:
                        pass
                        
            except Exception as e:
                logger.debug(f"Spider connection error to {relay}: {e}")

        tasks = [fetch_from_relay(relay) for relay in NostrSpider.SEARCH_RELAYS]
        await asyncio.gather(*tasks, return_exceptions=True)

        return results
