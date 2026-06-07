from typing import Any, Dict, List, Optional

from ..config import get_settings
from .hn_client import HackerNewsClient
from .logging_config import get_logger
from .reddit_client import RedditClient
from .rss_client import RSSClient

logger = get_logger(__name__)


class ResearchClient:
    """
    Multi-source research: Hacker News + RSS (primary), Reddit (optional).
    No API keys required for default operation.
    """

    def __init__(self, reddit_client: Optional[RedditClient] = None):
        self.hn = HackerNewsClient()
        self.rss = RSSClient()
        self.reddit = reddit_client or RedditClient()

    def get_relevant_subreddits(self, topic: str) -> List[str]:
        return self.reddit.get_relevant_subreddits(topic)

    def _dedupe_posts(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        unique: List[Dict[str, Any]] = []
        for post in posts:
            key = (post.get("title") or post.get("content", "")).strip().lower()[:120]
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(post)
        return unique

    def search_posts(
        self,
        query: str,
        subreddits: Optional[List[str]] = None,
        limit: int = 30,
        time_filter: str = "day",
    ) -> List[Dict[str, Any]]:
        per_source = max(limit // 2, 10)
        combined: List[Dict[str, Any]] = []

        try:
            hn_posts = self.hn.search_posts(query=query, limit=per_source)
            combined.extend(hn_posts)
            logger.info("Hacker News returned %s stories", len(hn_posts))
        except Exception as exc:
            logger.warning("Hacker News search failed: %s", exc)

        try:
            rss_posts = self.rss.search_posts(query=query, limit=per_source)
            combined.extend(rss_posts)
            logger.info("RSS returned %s articles", len(rss_posts))
        except Exception as exc:
            logger.warning("RSS search failed: %s", exc)

        settings = get_settings()
        if settings.is_reddit_api_configured():
            try:
                reddit_posts = self.reddit.search_posts(
                    query=query,
                    subreddits=subreddits,
                    limit=per_source,
                    time_filter=time_filter,
                )
                if reddit_posts:
                    combined.extend(reddit_posts)
                    logger.info("Reddit returned %s posts", len(reddit_posts))
            except Exception as exc:
                logger.warning("Reddit search failed: %s", exc)

        combined = self._dedupe_posts(combined)
        combined.sort(key=lambda p: p.get("engagement_score", 0), reverse=True)
        return combined[:limit]
