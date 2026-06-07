from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from .logging_config import get_logger
from .retry import retry_transient

logger = get_logger(__name__)

HN_API = "https://hacker-news.firebaseio.com/v0"


class HackerNewsClient:
    """Free public research fallback when Reddit API is unavailable."""

    @retry_transient(max_attempts=3, delay_seconds=1.0)
    def _fetch_item(self, item_id: int) -> Dict[str, Any]:
        resp = requests.get(f"{HN_API}/item/{item_id}.json", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def search_posts(
        self,
        query: str,
        limit: int = 20,
        **_,
    ) -> List[Dict[str, Any]]:
        resp = requests.get(f"{HN_API}/topstories.json", timeout=15)
        resp.raise_for_status()
        story_ids = resp.json()[: limit * 3]
        query_lower = query.lower()
        posts: List[Dict[str, Any]] = []

        for story_id in story_ids:
            try:
                item = self._fetch_item(story_id)
            except Exception as exc:
                logger.warning("HN item %s failed: %s", story_id, exc)
                continue
            if item.get("type") != "story":
                continue
            title = item.get("title") or ""
            if query_lower and query_lower not in title.lower():
                continue
            score = item.get("score", 0)
            comments = item.get("descendants", 0) or 0
            created = datetime.fromtimestamp(
                item.get("time", 0), tz=timezone.utc
            )
            posts.append({
                "post_id": str(item.get("id", "")),
                "title": title,
                "content": title,
                "author": item.get("by", "unknown"),
                "subreddit": "hackernews",
                "url": item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id')}",
                "permalink": f"https://news.ycombinator.com/item?id={item.get('id')}",
                "score": score,
                "num_comments": comments,
                "engagement_score": score + (comments * 2),
                "created_at": created,
                "is_self": True,
            })
            if len(posts) >= limit:
                break

        if not posts and story_ids:
            for story_id in story_ids[:limit]:
                try:
                    item = self._fetch_item(story_id)
                except Exception:
                    continue
                if item.get("type") != "story":
                    continue
                score = item.get("score", 0)
                comments = item.get("descendants", 0) or 0
                title = item.get("title") or ""
                posts.append({
                    "post_id": str(item.get("id", "")),
                    "title": title,
                    "content": title,
                    "author": item.get("by", "unknown"),
                    "subreddit": "hackernews",
                    "url": item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id')}",
                    "permalink": f"https://news.ycombinator.com/item?id={item.get('id')}",
                    "score": score,
                    "num_comments": comments,
                    "engagement_score": score + (comments * 2),
                    "created_at": datetime.fromtimestamp(
                        item.get("time", 0), tz=timezone.utc
                    ),
                    "is_self": True,
                })
        return posts
