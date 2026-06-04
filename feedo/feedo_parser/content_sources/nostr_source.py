import json
import uuid
import asyncio
import websockets
import hashlib
from datetime import datetime
from .base import BaseSource
from .text_utils import clean_html_text
from coincurve import PublicKeyXOnly
import logging

logger = logging.getLogger("nostr_source")


def _calc_nostr_event_id(event: dict) -> str:
    """NIP-01 canonical event id: sha256(JSON([0,pubkey,created_at,kind,tags,content]))."""
    canonical = [
        0, 
        event.get("pubkey", ""),
        event.get("created_at", 0),
        event.get("kind", 0),
        event.get("tags", []),
        event.get("content", ""),
    ]
    encoded = json.dumps(canonical, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _verify_nostr_event_signature(event: dict) -> bool:
    """NIP-01 + NIP-340 validation for Nostr event signatures."""
    ev_id = event.get("id", "")
    sig_hex = event.get("sig", "")
    pubkey_hex = event.get("pubkey", "")

    if (
        not isinstance(ev_id, str)
        or not isinstance(sig_hex, str)
        or not isinstance(pubkey_hex, str)
        or len(ev_id) != 64
        or len(sig_hex) != 128
        or len(pubkey_hex) != 64 
    ):
        return False

    # First validate the event id itself (anti-tamper check).
    if _calc_nostr_event_id(event) != ev_id:
        return False

    try:
        pubkey = PublicKeyXOnly(bytes.fromhex(pubkey_hex))
        return pubkey.verify(bytes.fromhex(sig_hex), bytes.fromhex(ev_id))
    except Exception:
        return False

class NostrSource(BaseSource):
    source_type = "nostr"
    RELAYS = [
        "wss://relay.damus.io",
        "wss://nos.lol",
        "wss://relay.primal.net"
    ]

    async def fetch_new(self, since: datetime | None) -> list[dict]:
        since_ts = int(since.timestamp()) if since else int(datetime.utcnow().timestamp()) - 3600
        sub_id = f"feedo_{uuid.uuid4().hex[:8]}"
        req = ["REQ", sub_id, {"kinds": [1], "since": since_ts, "limit": 100}]
        
        posts = []
        seen_ids = set()

        for relay_url in self.RELAYS:
            accepted_count = 0
            invalid_count = 0
            try:
                async with websockets.connect(relay_url, open_timeout=5, close_timeout=5) as ws:
                    await ws.send(json.dumps(req))
                    
                    while True:
                        try:
                            msg_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            msg = json.loads(msg_str)
                            
                            if msg[0] == "EOSE" and msg[1] == sub_id:
                                break # Кінець даних з цього релею
                                
                            if msg[0] == "EVENT" and msg[1] == sub_id:
                                event = msg[2]
                                ev_id = event["id"]
                                
                                if ev_id in seen_ids:
                                    continue
                                seen_ids.add(ev_id)
                                
                                # Перевірка підпису від спаму
                                if not _verify_nostr_event_signature(event):
                                    invalid_count += 1
                                    continue
                                accepted_count += 1

                                # Пошук тегу 'e' (означає реплай)
                                is_reply = any(tag[0] == "e" for tag in event.get("tags", []))
                                
                                pub_date = datetime.utcfromtimestamp(event["created_at"])
                                
                                posts.append({
                                    "source_specific_id": ev_id,
                                    "text_content": clean_html_text(event["content"]),
                                    "author_address": event["pubkey"], # Для Nostr це pubkey
                                    "original_author_name": f"Nostr:{event['pubkey'][:8]}",
                                    "signature": event["sig"],
                                    "hash_id": ev_id,
                                    "published_at": pub_date,
                                    "metadata_": {
                                        "relay": relay_url,
                                        "is_reply": is_reply,
                                        "tags": event.get("tags", [])
                                    }
                                })
                        except asyncio.TimeoutError:
                            break # Якщо релей мовчить 5 сек - йдемо далі
                if invalid_count > 0:
                    logger.info(
                        "Nostr relay %s: accepted=%d skipped_invalid=%d",
                        relay_url,
                        accepted_count,
                        invalid_count,
                    )
            except Exception as e:
                logger.error(f"Помилка підключення до релею {relay_url}: {e}")
                
        return posts
