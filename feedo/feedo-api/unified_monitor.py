import os
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
from feedo_parser.content_sources import RSSSource, NostrSource, HNSource
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
RSS_NODE_WALLET = os.getenv("RSS_NODE_WALLET", "feedo_system_node_wallet_address_here")

GLOBAL_REGISTRY_URL = "https://raw.githubusercontent.com/Ashixi/feedo-sources/825d8d28815a12ab61a347aa7893773949f3ca0c/analyzed_sources.json"

SOURCES = [
    RSSSource(),
    HNSource(),
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

    payload = {
        "text": p_data["text_content"],
        "author": RSS_NODE_WALLET,
        "signature": sig,
        "hash_id": h_id,
        "content_blob_hash": p_data["content_blob_hash"],
        "prev_post_hash": "", 
        "sequence_number": 0,
        "skip_dht_upload": skip_dht_upload
    }

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(RUST_CORE_URL, json=payload, timeout=10.0)
            return res.status_code == 200
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

async def sync_global_sources(db):
    logger.info("Стягування глобального реєстру джерел...")
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(GLOBAL_REGISTRY_URL, timeout=15.0)
            if res.status_code == 200:
                sources_data = res.json()
                
                for s_data in sources_data:
                    stmt = select(Source).where(Source.external_id == s_data["url"])
                    existing = (await db.execute(stmt)).scalar_one_or_none()
                    
                    if not existing:
                        new_source = Source(
                            external_id=s_data["url"],
                            source_type=SourceTypeEnum.RSS,
                            name=s_data.get("source_summary", "Unknown feed")[:50],
                            language=s_data.get("language", "en")
                        )
                        db.add(new_source)
                await db.commit()
                logger.info(f"Реєстр синхронізовано. В базі {len(sources_data)} відкритих джерел.")
    except Exception as e:
        logger.error(f"Помилка синхронізації джерел: {e}")

async def process_source(source):
    try:
        async with AsyncSessionLocal() as db:
            source_type = _normalize_source_type(source.source_type)
            logger.info(f"Парсинг джерела: {source_type}")
            is_rss = source_type == "rss"
            commit_batch_size = 200 if is_rss else 0
            chunk_size = 64 if is_rss else 0
            pending_inserts = 0
            rss_source_map = {}
            if is_rss:
                stmt_sources = select(Source).where(Source.source_type == SourceTypeEnum.RSS)
                db_sources = (await db.execute(stmt_sources)).scalars().all()
                rss_source_map = {s.external_id: s.id for s in db_sources}
            
            stmt_last_post = select(func.max(Post.published_at)).where(Post.source_type == source_type)
            last_post_date = (await db.execute(stmt_last_post)).scalar()
            
            raw_posts = await source.fetch_new(since=last_post_date)
            logger.info(f"Знайдено {len(raw_posts)} нових елементів у {source.source_type}")
            
            new_count = 0
            updated_count = 0
            
            valid_posts = []
            
            local_media_storage = LocalMediaStorage()
            
            for p_data in raw_posts:
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

                    new_post = Post(
                        source_id=source_id,
                        source_type=source_type,
                        source_specific_id=p_data["source_specific_id"],
                        title=p_data.get("title"),
                        text_content=p_data["text_content"],
                        author_address=p_data.get("author_address", RSS_NODE_WALLET),
                        original_author_name=p_data.get("original_author_name"),
                        external_link=p_data.get("external_link"),
                        published_at=_to_naive_utc(p_data["published_at"]),
                        language=p_data.get("language", "uk"),
                        metadata_=p_data.get("metadata_", {}),
                        hash_id=p_data.get("hash_id"),
                        content_blob_hash=p_data["content_blob_hash"],
                        signature=p_data.get("signature"),
                        parent_post_id=parent_id,
                        is_repost=bool(parent_id)
                    )

                    db.add(new_post)
                    await db.flush()
                    pending_inserts += 1

                    if vector is not None and not parent_id and source_type != "media_blob":
                        geo = (p_data.get("metadata_") or {}).get("geo", "")
                        brain.add_vector_by_emb(
                            new_post.id,
                            new_post.hash_id,
                            vector,
                            source_type,
                            language=new_post.language or "",
                            geo=geo,
                        )

                    logger.info(f"Трансляція нового посту з {source_type} у мережу Feedo...")
                    await broadcast_to_p2p(p_data, skip_dht_upload=skip_dht_upload)

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
        logger.error(f"Помилка під час обробки {getattr(source, 'source_type', 'unknown')}: {e}")

async def monitor_all(stop_event: threading.Event | None = None):
    logger.info("Запуск Unified Monitor")
    try:
        global brain
        if brain is None:
            logger.info("Ініціалізація VectorBrain всередині монітора (lazy load)...")
            brain = VectorBrain()
        while True:
            async with AsyncSessionLocal() as db:
                await sync_global_sources(db)
                
                stmt = select(Source).where(Source.source_type == SourceTypeEnum.RSS)
                db_sources = (await db.execute(stmt)).scalars().all()
                
                rss_feed_list = [{"url": s.external_id, "name": s.name, "lang": s.language} for s in db_sources]
            
            rss_source_instance = next((s for s in SOURCES if isinstance(s, RSSSource)), None)
            if rss_source_instance:
                rss_source_instance.set_feeds(rss_feed_list)

            net_info = await get_network_info()
            peer_id = net_info.get("peer_id", "standalone_node")
            total_nodes = max(1, net_info.get("total_nodes", 1))

            my_id_num = int(hashlib.sha256(peer_id.encode('utf-8')).hexdigest(), 16)
            
            active_sources = []
            for index, source in enumerate(SOURCES):
                if (index % total_nodes) == (my_id_num % total_nodes):
                    active_sources.append(source)
                    
            logger.info(f"Sharding: Моя нода {peer_id[:8]}... Всього нод: {total_nodes}. "
                        f"Беру в обробку {len(active_sources)}/{len(SOURCES)} протоколів.")
            
            if active_sources:
                tasks = [process_source(source) for source in active_sources]
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