from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import quote
import email.utils

import feedparser

from .logging_config import get_logger
from .retry import retry_transient

logger = get_logger(__name__)

STATIC_FEEDS = [
    ("bbc_news", "http://feeds.bbci.co.uk/news/rss.xml"),
    ("bbc_technology", "http://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("bbc_business", "http://feeds.bbci.co.uk/news/business/rss.xml"),
]


class RSSClient:
    """RSS news research — no API keys required."""

    def _parse_date(self, entry: Dict[str, Any]) -> datetime:
        for key in ("published_parsed", "updated_parsed"):
            parsed = entry.get(key)
            if parsed:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
        raw = entry.get("published") or entry.get("updated") or ""
        if raw:
            try:
                return email.utils.parsedate_to_datetime(raw).astimezone(timezone.utc)
            except (TypeError, ValueError):
                pass
        return datetime.now(timezone.utc)

    def _entry_to_post(self, entry: Dict[str, Any], source: str) -> Dict[str, Any]:
        title = (entry.get("title") or "").strip()
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        if len(summary) > 500:
            summary = summary[:500]
        content = title
        if summary and summary != title:
            content = f"{title}\n\n{summary}"
        link = entry.get("link") or ""
        post_id = entry.get("id") or link or title[:80]
        return {
            "post_id": str(post_id),
            "title": title,
            "content": content,
            "author": entry.get("author", source),
            "subreddit": source,
            "url": link,
            "permalink": link,
            "score": 50,
            "num_comments": 0,
            "engagement_score": 50,
            "created_at": self._parse_date(entry),
            "is_self": True,
        }

    @retry_transient(max_attempts=2, delay_seconds=1.0)
    def _parse_feed(self, url: str) -> List[Dict[str, Any]]:
        parsed = feedparser.parse(url)
        return list(parsed.entries)

    def search_posts(
        self,
        query: str,
        limit: int = 20,
        **_,
    ) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        feeds = [
            ("google_news", f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"),
            *STATIC_FEEDS,
        ]
        posts: List[Dict[str, Any]] = []
        seen_titles: set[str] = set()

        for source, url in feeds:
            try:
                entries = self._parse_feed(url)
            except Exception as exc:
                logger.warning("RSS feed %s failed: %s", source, exc)
                continue
            for entry in entries:
                title = (entry.get("title") or "").strip()
                if not title or title.lower() in seen_titles:
                    continue
                if query_lower and query_lower not in title.lower():
                    summary = (entry.get("summary") or "").lower()
                    if query_lower not in summary:
                        continue
                seen_titles.add(title.lower())
                posts.append(self._entry_to_post(entry, source))
                if len(posts) >= limit:
                    return posts

        if not posts:
            for source, url in feeds[:2]:
                try:
                    for entry in self._parse_feed(url)[:limit]:
                        title = (entry.get("title") or "").strip()
                        if title and title.lower() not in seen_titles:
                            seen_titles.add(title.lower())
                            posts.append(self._entry_to_post(entry, source))
                            if len(posts) >= limit:
                                break
                except Exception:
                    continue
        return posts
