import asyncio
import httpx
import logging
import re
from typing import Optional

from media_storage import LocalMediaStorage

logger = logging.getLogger("media_downloader")

async def download_and_store_media(url: str, storage: LocalMediaStorage) -> Optional[str]:
    if not url or not url.startswith("http"):
        return None
        
    valid_exts = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
    if not any(url.lower().split('?')[0].endswith(ext) for ext in valid_exts):
        logger.debug(f"Ігнорую не-медіа посилання: {url}")
        return None
        
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers) as client:
            res = await client.get(url)
            if res.status_code == 200:
                content_type = res.headers.get("Content-Type", "application/octet-stream")
                media_id = await storage.upload(res.content, content_type)
                logger.info(f"Завантажено зображення {url} -> {media_id}")
                return media_id
    except Exception as e:
        logger.warning(f"Не вдалося завантажити зображення {url}: {e}")
    return None

async def parse_and_store_post_media(p_data: dict, storage: LocalMediaStorage):

    metadata = p_data.get("metadata_", {})
    
    external_url = metadata.get("external_media_url")
    if external_url and isinstance(external_url, str) and external_url.startswith("http"):
        media_id = await download_and_store_media(external_url, storage)
        if media_id:
            metadata["media_hash"] = media_id
            if "external_media_url" in metadata:
                del metadata["external_media_url"]
            
    text_content = p_data.get("text_content", "")
    if text_content:
        pattern = r'!\[([^\]]*)\]\((https?://[^)]+)\)'
        
        async def replace_match(match):
            alt_text = match.group(1)
            img_url = match.group(2)
            
            # Prevent downloading HTML pages or RSS feeds posted by users
            valid_exts = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
            if not any(img_url.lower().split('?')[0].endswith(ext) for ext in valid_exts):
                return match.group(0)
                
            media_id = await download_and_store_media(img_url, storage)
            if media_id:
                return f"![{alt_text}](/p2p-media/{media_id})"
            return match.group(0)
        
        matches = list(re.finditer(pattern, text_content))
        if matches:
            logger.info(f"Знайдено {len(matches)} markdown зображень для обробки...")
            offset = 0
            new_text = ""
            for match in matches:
                start, end = match.span()
                new_text += text_content[offset:start]
                replacement = await replace_match(match)
                new_text += replacement
                offset = end
            new_text += text_content[offset:]
            p_data["text_content"] = new_text
