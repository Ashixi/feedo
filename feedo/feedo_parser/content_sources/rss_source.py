import calendar
import logging
import asyncio
import re
from datetime import datetime

import feedparser
import httpx
from urllib.parse import urljoin

import trafilatura

from .base import BaseSource
from .text_utils import clean_plain_text, clean_html_text

logger = logging.getLogger("rss_source")

class RSSSource(BaseSource):
    source_type = "rss"
    
    def __init__(self):
        self.feeds = []

    async def _fetch_article_text(self, url: str) -> dict:
        """Fetch article HTML and extract readable text (via trafilatura) and first media.

        Returns dict with keys: text, media_url, media_type
        """
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            try:
                res = await client.get(url)
                res.raise_for_status()

                # Extract media metadata (og:image / og:video / first img/video)
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(res.text, "html.parser")

                media_url = None
                media_type = None
                og_image = soup.find("meta", property="og:image")
                if og_image and og_image.get("content"):
                    media_url = og_image.get("content")
                    media_type = "image/*"

                if not media_url:
                    og_video = soup.find("meta", property="og:video")
                    if og_video and og_video.get("content"):
                        media_url = og_video.get("content")
                        media_type = "video/*"

                if not media_url:
                    img = soup.find("img", src=True)
                    if img:
                        media_url = img.get("src")
                        media_type = "image/*"

                if not media_url:
                    vid = soup.find("video")
                    if vid:
                        src = vid.get("src")
                        if not src:
                            source = vid.find("source", src=True)
                            src = source.get("src") if source else None
                        if src:
                            media_url = src
                            media_type = "video/*"

                # Prefer GitHub README for repos
                if "github.com" in url.lower():
                    gh = await self._fetch_github_readme(url)
                    if gh:
                        return {"text": gh, "media_url": media_url, "media_type": media_type}

                # Use trafilatura via clean_html_text (run in a thread)
                try:
                    text = await asyncio.to_thread(clean_html_text, res.text)
                except Exception:
                    text = ""

                return {"text": text, "media_url": media_url, "media_type": media_type}
            except Exception:
                return {"text": "", "media_url": None, "media_type": None}

    async def _fetch_github_readme(self, url: str) -> str:
        try:
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
        except Exception:
            pass
        return ""

    def set_feeds(self, feeds: list[dict]):
        self.feeds = feeds

    def _clean_text(self, value: str) -> str:
        return clean_plain_text(value)

    async def fetch_new(self, since: datetime | None) -> list[dict]:
        headers = {"User-Agent": "Mozilla/5.0"}
        posts = []
        
        if not self.feeds:
            return posts
            
        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            for feed in self.feeds:
                try:
                    res = await client.get(feed["url"])
                    res.raise_for_status()
                    parsed = feedparser.parse(res.text)
                    
                    for entry in parsed.entries:
                        pub_date = self._parse_date(entry.get("published_parsed"))
                        if since and pub_date <= since:
                            continue

                        link = entry.get("link")
                        title = self._clean_text(entry.get("title", "No title"))
                        summary = self._clean_text(entry.get("summary", ""))

                        # Try to fetch full article text and media when link is available
                        article_text = ""
                        media_url = None
                        media_type = None
                        if link:
                            try:
                                fetched = await self._fetch_article_text(link)
                                article_text = fetched.get("text", "") or ""
                                media_url = fetched.get("media_url")
                                media_type = fetched.get("media_type")
                                # Normalize relative media URLs
                                if media_url:
                                    media_url = urljoin(link, media_url)
                            except Exception:
                                article_text = ""

                        # RSS content fallback: use title + summary if article text is too short
                        if article_text and len(article_text) > 150:
                            content = article_text
                        else:
                            content = f"{title}. {summary}" if summary else title

                        # Шукаємо enclosures / media_content в entry as fallback
                        meta = {"feed_name": feed["name"], "feed_url": feed["url"]}
                        if getattr(entry, 'media_content', None):
                            try:
                                mc = entry.media_content
                                if isinstance(mc, list) and len(mc) > 0:
                                    media_url = media_url or (mc[0].get('url') or mc[0].get('href'))
                                    media_type = media_type or mc[0].get('type')
                            except Exception:
                                pass

                        if not media_url and entry.get('enclosures'):
                            enc = entry.get('enclosures')
                            if isinstance(enc, list) and len(enc) > 0:
                                media_url = media_url or (enc[0].get('href') or enc[0].get('url'))
                                media_type = media_type or enc[0].get('type')

                        if media_url:
                            meta.update({
                                'external_media_url': media_url,
                                'media_mime_type': media_type,
                                'media_name': media_url.split('/')[-1]
                            })

                        posts.append({
                            "source_specific_id": f'{feed["url"]}::{entry.get("id", link)}',
                            "title": title,
                            "text_content": content,
                            "original_author_name": entry.get("author") or feed["name"],
                            "external_link": link,
                            "published_at": pub_date,
                            "language": feed.get("lang", "en"),
                            "metadata_": meta
                        })
                except Exception as e:
                    logger.error(f"Помилка RSS {feed['url']}: {e}")
                    
        return sorted(posts, key=lambda x: x["published_at"], reverse=True)

    def _parse_date(self, entry_date):
        if hasattr(entry_date, 'tm_year'):
            timestamp = calendar.timegm(entry_date)
            return datetime.utcfromtimestamp(timestamp)
        return datetime.utcnow()
