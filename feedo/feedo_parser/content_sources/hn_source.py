import asyncio
import re
import httpx
import trafilatura
from datetime import datetime
from .base import BaseSource
from .text_utils import clean_plain_text, clean_html_text
import logging

logger = logging.getLogger("hn_source")

class HNSource(BaseSource): 
    source_type = "hn"
    BASE_URL = "https://hacker-news.firebaseio.com/v0"

    async def fetch_article_text(self, url: str) -> str:
        """Fetch readable article text for a URL.

        Uses a domain-specific handler for GitHub (returns README.md via API)
        and falls back to `trafilatura` for generic sites. Heavy I/O/CPU work
        is run via `asyncio.to_thread` to avoid blocking the event loop.
        """
        if not url:
            return ""
        try:
            # GitHub repositories are common on HN; prefer README via API
            if "github.com" in url.lower():
                gh = await self._fetch_github_readme(url)
                if gh:
                    return gh

            # Fetch using httpx with User-Agent to bypass 403 blocks, then extract via clean_html_text
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            try:
                async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
                    res = await client.get(url)
                    if res.status_code == 200:
                        extracted = await asyncio.to_thread(clean_html_text, res.text)
                        if extracted:
                            return extracted
            except Exception as e:
                logger.debug(f"HTTP fetch failed for {url}: {e}")

            # Nothing useful found
            return ""
        except Exception as e:
            logger.warning(f"Не вдалося спарсити статтю {url}: {e}")
            return ""

    async def _fetch_github_readme(self, url: str) -> str:
        """Try to retrieve repository README via GitHub API (raw markdown).

        Returns raw markdown string or empty string on failure.
        """
        try:
            # match owner/repo from various github URL shapes
            m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", url, re.IGNORECASE)
            if not m:
                return ""
            owner, repo = m.group(1), m.group(2)
            repo = repo.rstrip('/')

            api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
            headers = {"Accept": "application/vnd.github.v3.raw"}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                res = await client.get(api_url, headers=headers)
                if res.status_code == 200:
                    return res.text or ""
                # If we got a redirect to raw content or rate-limited, try unauthenticated raw fetch
                if res.status_code in (302, 301) and res.headers.get("location"):
                    try:
                        r2 = await client.get(res.headers.get("location"))
                        if r2.status_code == 200:
                            return r2.text or ""
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"GitHub README fetch failed for {url}: {e}")
        return ""

    async def fetch_new(self, since: datetime | None) -> list[dict]:
        posts = []
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                res = await client.get(f"{self.BASE_URL}/newstories.json")
                res.raise_for_status()
                # Зменшуємо до 30, оскільки тепер ми ходимо по сторонніх сайтах
                story_ids = res.json()[:30] 
                
                for sid in story_ids:
                    item_res = await client.get(f"{self.BASE_URL}/item/{sid}.json")
                    if item_res.status_code != 200:
                        continue
                    
                    item = item_res.json()
                    if not item or item.get("type") != "story":
                        continue
                        
                    pub_date = datetime.utcfromtimestamp(item.get("time", 0))
                    if since and pub_date <= since:
                        continue 
                        
                    title = clean_plain_text(item.get("title", ""))
                    url = item.get("url")
                    hn_text = clean_plain_text(item.get("text", ""))
                    
                    # Йдемо по URL за повним текстом
                    article_text = ""
                    if url:
                        article_text = await self.fetch_article_text(url)
                    
                    # Якщо сайт заблокував запит або тексту мало - беремо опис з самого HN
                    final_text = article_text if len(article_text) > 150 else hn_text
                    
                    # Якщо тексту взагалі немає, лишаємо заголовок як контент
                    if not final_text:
                        final_text = title
                    
                    posts.append({
                        "source_specific_id": str(item["id"]),
                        "title": title, # Зберігаємо заголовок окремо
                        "text_content": final_text,
                        "original_author_name": item.get("by"),
                        "external_link": url,
                        "published_at": pub_date,
                        "language": "en",
                        "metadata_": {
                            "score": item.get("score", 0),
                            "comments_count": item.get("descendants", 0)
                        }
                    })
            except Exception as e:
                logger.error(f"Помилка HackerNews: {e}")
                
        return posts
