import os
import re
import asyncio
import logging
import httpx
import hashlib
import threading
from datetime import timezone
from sqlalchemy import func, select

from database import AsyncSessionLocal
from models import Post, Source, SourceTypeEnum
from feedo_parser.vector_brain import VectorBrain
from feedo_parser.content_sources import NostrSource
from feedo_parser.content_sources.text_utils import sanitize_for_storage
from feedo_parser.crypto_utils import sign_hash, generate_hash_id, generate_content_hash
from media_storage import LocalMediaStorage
from media_downloader import parse_and_store_post_media

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("unified_monitor")

CHECK_INTERVAL = 300 
brain = None

RUST_CORE_URL = os.getenv("RUST_CORE_URL", "http://127.0.0.1:8041/local/publish")
RUST_NETWORK_INFO_URL = os.getenv("RUST_NETWORK_INFO_URL", "http://127.0.0.1:8041/local/network_info")

RSS_NODE_SECRET = os.getenv("RSS_NODE_SECRET", "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")
import nacl.signing
_sk_bytes = bytes.fromhex(RSS_NODE_SECRET)
if len(_sk_bytes) == 64:
    _sk_bytes = _sk_bytes[:32]
RSS_NODE_WALLET = os.getenv("RSS_NODE_WALLET", bytes(nacl.signing.SigningKey(_sk_bytes).verify_key).hex())

GLOBAL_REGISTRY_URL = "https://raw.githubusercontent.com/Ashixi/feedo-sources/825d8d28815a12ab61a347aa7893773949f3ca0c/analyzed_sources.json"

SOURCES = [
    # Uncomment the source below if you want to run a dedicated parsing node
    NostrSource()
]


def _to_naive_utc(value):
    if value is None:
        return value
    if getattr(value, "tzinfo", None) is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _normalize_source_type(source_type) -> str:
    if hasattr(source_type, "value"):
        return str(source_type.value).lower()
    return str(source_type).lower()

async def broadcast_to_p2p(p_data: dict, skip_dht_upload: bool = False):
    h_id = generate_hash_id(p_data["text_content"], p_data["published_at"])
    sig = sign_hash(h_id, RSS_NODE_SECRET)

    try:
        import feedo_pb2
        import json
        pb_req = feedo_pb2.PublishRequest(
            text=p_data["text_content"],
            author=RSS_NODE_WALLET,
            signature=sig,
            hash_id=h_id,
            content_blob_hash=p_data.get("content_blob_hash", ""),
            prev_post_hash="", 
            sequence_number=0,
            skip_dht_upload=skip_dht_upload,
            source_type=p_data.get("source_type", "nostr"),
            metadata=json.dumps(p_data.get("metadata_", {}))
        )
        async with httpx.AsyncClient() as client:
            res = await client.post(
                RUST_CORE_URL, 
                content=pb_req.SerializeToString(), 
                headers={"Content-Type": "application/x-protobuf"},
                timeout=10.0
            )
            return res.status_code in (200, 201)
    except Exception as e:
        logger.error(f"Не вдалося відправити в P2P (Rust Core недоступний?): {e}")
        return False

async def get_network_info():
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(RUST_NETWORK_INFO_URL, timeout=5.0)
            if res.status_code == 200 and res.json():
                return res.json()
    except Exception as e:
        logger.error(f"Не вдалося отримати network info від Rust: {e}")
    return {"peer_id": "standalone_node", "total_nodes": 1}



async def get_network_sync_state(source_type: str) -> float:
    try:
        url = f"http://127.0.0.1:8041/local/network_sync_state/{source_type}"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10.0)
            if res.status_code == 200:
                data = res.json()
                if data.get("max_timestamp"):
                    return float(data["max_timestamp"])
    except Exception as e:
        logger.error(f"Не вдалося отримати стан мережі для {source_type}: {e}")
    return 0.0

async def process_source(source, node_index: int = 0, total_nodes: int = 1):
    try:
        async with AsyncSessionLocal() as db:
            source_type = _normalize_source_type(source.source_type)
            logger.info(f"Парсинг джерела: {source_type}")
            is_rss = source_type == "rss"
            commit_batch_size = 100
            chunk_size = 64
            pending_inserts = 0
            rss_source_map = {}
            if is_rss:
                stmt_sources = select(Source).where(Source.source_type == SourceTypeEnum.RSS)
                db_sources = (await db.execute(stmt_sources)).scalars().all()
                rss_source_map = {s.external_id: s.id for s in db_sources}
            
            stmt_last_post = select(func.max(Post.published_at)).where(Post.source_type == source_type)
            last_post_date = (await db.execute(stmt_last_post)).scalar()

            net_max_ts = await get_network_sync_state(source_type)
            if net_max_ts > 0:
                from datetime import datetime, timezone
                net_date = datetime.fromtimestamp(net_max_ts, tz=timezone.utc).replace(tzinfo=None)
                if not last_post_date or net_date > last_post_date:
                    logger.info(f"Використовуємо мережевий курсор: {net_date}")
                    last_post_date = net_date
            
            is_batched = hasattr(source, "fetch_new_batches")
            if is_batched:
                generator = source.fetch_new_batches(since=last_post_date, node_index=node_index, total_nodes=total_nodes, db=db)
            else:
                async def fallback_gen():
                    yield await source.fetch_new(since=last_post_date)
                generator = fallback_gen()
            
            new_count = 0
            updated_count = 0
            
            async for raw_posts in generator:
                logger.info(f"Знайдено {len(raw_posts)} нових елементів у батчі з {source.source_type}")
            
                valid_posts = []
                local_media_storage = LocalMediaStorage()
                
                # Deduplicate raw_posts in memory to prevent IntegrityError
                seen_in_batch = set()
                deduped_raw_posts = []
                for p_data in raw_posts:
                    sid = p_data.get("source_specific_id")
                    if sid in seen_in_batch:
                        continue
                    seen_in_batch.add(sid)
                    deduped_raw_posts.append(p_data)
                
                for p_data in deduped_raw_posts:
                    p_data["text_content"] = sanitize_for_storage(p_data.get("text_content", ""))
                    if not p_data["text_content"]:
                        logger.info(f"␡ Пропущено після санітизації: {p_data.get('source_specific_id')}")
                        continue
                    stmt_exists = select(Post).where(
                        Post.source_type == source_type,
                        Post.source_specific_id == p_data["source_specific_id"]
                    )
                    existing_post = (await db.execute(stmt_exists)).scalar_one_or_none()
                    
                    if existing_post:
                        existing_post.metadata_ = p_data.get("metadata_", existing_post.metadata_)
                        updated_count += 1
                        logger.info(f"↺ Сховано/оновлено існуючий пост (source_specific_id={p_data.get('source_specific_id')})")
                        logger.info(
                            "[decision] existing -> reason=existing source_specific_id=%s len=%d",
                            p_data.get("source_specific_id"),
                            len(p_data.get("text_content") or ""),
                        )
                        continue
    
                    if brain.is_gibberish(p_data["text_content"]):
                        logger.info(f"␡ Пропущено gibberish: {p_data.get('source_specific_id')} (len={len(p_data.get('text_content') or '')})")
                        logger.info(
                            "[decision] skipped -> reason=gibberish source_specific_id=%s len=%d",
                            p_data.get("source_specific_id"),
                            len(p_data.get("text_content") or ""),
                        )
                        continue
                        
                    content_blob_hash = generate_content_hash(p_data["text_content"])
                    p_data["content_blob_hash"] = content_blob_hash
    
                    stmt_exact = select(Post).where(Post.content_blob_hash == content_blob_hash).order_by(Post.published_at).limit(1)
                    exact_match = (await db.execute(stmt_exact)).scalar_one_or_none()
    
                    if not exact_match:
                        await parse_and_store_post_media(p_data, local_media_storage)
    
                    p_data["exact_match"] = exact_match
                    valid_posts.append(p_data)
    
                for chunk_start in range(0, len(valid_posts), chunk_size or len(valid_posts) or 1):
                    chunk_posts = valid_posts[chunk_start:chunk_start + (chunk_size or len(valid_posts) or 1)]
                    chunk_texts = [p_data["text_content"] for p_data in chunk_posts if not p_data.get("exact_match")]
    
                    chunk_embeddings = [] 
                    if chunk_texts:
                        chunk_embeddings = await brain.get_embeddings_batch_async(chunk_texts, batch_size=32)
    
                    emb_idx = 0
                    for p_data in chunk_posts:
                        exact_match = p_data.pop("exact_match")
                        parent_id = None
                        skip_dht_upload = False
                        vector = None
                        source_id = None
    
                        if is_rss:
                            feed_url = (p_data.get("metadata_") or {}).get("feed_url")
                            if feed_url:
                                source_id = rss_source_map.get(feed_url)
                                if source_id is None:
                                    logger.info(f"RSS feed not found in DB map: {feed_url} for entry {p_data.get('source_specific_id')}" )
    
                        if exact_match:
                            parent_id = exact_match.parent_post_id or exact_match.id
                            skip_dht_upload = True
                            logger.info(
                                "[decision] exact_match -> reason=exact_duplicate source_specific_id=%s parent_id=%s len=%d",
                                p_data.get("source_specific_id"),
                                parent_id,
                                len(p_data.get("text_content") or ""),
                            )
                        else:
                            vector = chunk_embeddings[emb_idx]
                            emb_idx += 1
                            parent_hash = brain.find_duplicate_by_vector(vector, threshold=0.95, hours=24)
                            parent_id = None
                            if parent_hash:
                                stmt_parent_check = select(Post.id).where(Post.hash_id == parent_hash)
                                parent_id = (await db.execute(stmt_parent_check)).scalar_one_or_none()
                                if not parent_id:
                                    logger.info(f"Vector duplicate points to missing post hash {parent_hash}; skipping parent linkage.")
                                    logger.info(
                                        "[decision] vector_duplicate -> reason=vector_parent_missing source_specific_id=%s parent_ref=%s len=%d",
                                        p_data.get("source_specific_id"),
                                        parent_hash,
                                        len(p_data.get("text_content") or ""),
                                    )
                                else:
                                    logger.info(
                                        "[decision] vector_duplicate -> reason=vector_parent_exists source_specific_id=%s parent_id=%s len=%d",
                                        p_data.get("source_specific_id"),
                                        parent_id,
                                        len(p_data.get("text_content") or ""),
                                    )
    
                        if parent_id:
                            logger.info(f"Дублікат з {source_type}! Пришито до ID: {parent_id} (source_specific_id={p_data.get('source_specific_id')})")
    
                        if not parent_id:
                            logger.info(
                                "[decision] insert -> reason=unique_insert source_specific_id=%s len=%d",
                                p_data.get("source_specific_id"),
                                len(p_data.get("text_content") or ""),
                            )
    
                        # Stateless Indexer: if relay_url is present, we drop text_content
                        relay_url = p_data.get("relay_url") or (p_data.get("metadata_") or {}).get("relay")
                        db_text_content = None if relay_url else p_data.get("text_content")
                        item_type = p_data.get("item_type", "post")
    
                        new_post = Post(
                            source_id=source_id,
                            source_type=source_type,
                            source_specific_id=p_data["source_specific_id"],
                            title=p_data.get("title"),
                            text_content=db_text_content,
                            author_address=p_data.get("author_address", RSS_NODE_WALLET),
                            original_author_name=p_data.get("original_author_name"),
                            external_link=p_data.get("external_link"),
                            relay_url=relay_url,
                            published_at=_to_naive_utc(p_data["published_at"]),
                            language=p_data.get("language", "uk"),
                            metadata_=p_data.get("metadata_", {}),
                            hash_id=p_data.get("hash_id"),
                            content_blob_hash=p_data["content_blob_hash"],
                            signature=p_data.get("signature"),
                            parent_post_id=parent_id,
                            is_repost=bool(parent_id),
                            item_type=item_type
                        )
    
                        db.add(new_post)
                        await db.flush()
                        pending_inserts += 1
    
                        if vector is not None and not parent_id and source_type != "media_blob":
                            geo = (p_data.get("metadata_") or {}).get("geo", "")
                            
                            # Multimodal Image Vectorization
                            image_vector = None
                            
                            # First try explicit image_url from parser
                            img_url = p_data.get("image_url")
                            
                            if not img_url:
                                # Fallback: Find first image link in text
                                text_content = p_data.get("text_content", "") or ""
                                img_match = re.search(r'(https?://[^\s]+(?:jpg|jpeg|png|webp))', text_content, re.IGNORECASE)
                                if img_match:
                                    img_url = img_match.group(1)
                                    
                            if img_url:
                                logger.info(f"📸 Знайдено зображення для векторизації: {img_url}")
                                image_vector = await brain.get_image_embedding_async(img_url)
                                
                            brain.add_vector_by_emb(
                                post_id=new_post.id,
                                hash_id=new_post.hash_id,
                                vector=vector,
                                source_type=source_type,
                                item_type=item_type,
                                language=new_post.language or "",
                                geo=geo,
                                relay_url=relay_url or "",
                                image_vector=image_vector
                            )
    
                        # logger.info(f"Трансляція нового посту з {source_type} у мережу Feedo...")
                        # await broadcast_to_p2p(p_data, skip_dht_upload=skip_dht_upload)
    
                        new_count += 1
    
                        if commit_batch_size and pending_inserts >= commit_batch_size:
                            await db.commit()
                            logger.info(
                                "%s: Проміжний commit (%d нових)",
                                source_type,
                                new_count,
                            )
                            pending_inserts = 0
    
                    if is_rss and pending_inserts:
                        await db.commit()
                        logger.info(
                            "%s: RSS chunk commit (%d нових)",
                            source_type,
                            new_count,
                        )
                        pending_inserts = 0
    
            await db.commit()
            logger.info(f"{source_type}: Додано {new_count}, Оновлено {updated_count}.")
            
    except Exception as e:
        logger.error(f"Помилка під час обробки {getattr(source, 'source_type', 'unknown')}: {e}", exc_info=True)

async def monitor_all(stop_event: threading.Event | None = None):
    logger.info("Запуск Unified Monitor")
    try:
        global brain
        if brain is None:
            logger.info("Ініціалізація VectorBrain всередині монітора (lazy load)...")
            brain = VectorBrain()
        while True:


            net_info = await get_network_info()
            peer_id = net_info.get("peer_id", "standalone_node")
            total_nodes = max(1, net_info.get("total_nodes", 1))

            my_id_num = int(hashlib.sha256(peer_id.encode('utf-8')).hexdigest(), 16)
            node_index = my_id_num % total_nodes
                    
            logger.info(f"Sharding: Моя нода {peer_id[:8]}... Всього нод: {total_nodes}. "
                        f"Індекс ноди: {node_index}. Оброблюємо всі протоколи з внутрішнім шардингом.")
            
            tasks = [process_source(source, node_index, total_nodes) for source in SOURCES]
            await asyncio.gather(*tasks)
            
            await asyncio.sleep(CHECK_INTERVAL)
            if stop_event is not None and stop_event.is_set():
                logger.info("Stop event set; breaking monitor loop.")
                break
    except asyncio.CancelledError:
        logger.info("Роботу монітора перервано (сервер зупиняється).")

if __name__ == "__main__":
    try:
        asyncio.run(monitor_all())
    except KeyboardInterrupt:
        logger.info("Зупинка монітора...")


def run_monitor_process(stop_event: threading.Event | None = None):
    try:
        asyncio.run(monitor_all(stop_event=stop_event))
    except KeyboardInterrupt:
        logger.info("Monitor process received KeyboardInterrupt; exiting.")