"""
Reddit API client wrapper.
Uses official PRAW when credentials exist, otherwise public JSON endpoints.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

import requests

from ..config import get_settings
from .logging_config import get_logger
from .retry import retry_transient

logger = get_logger(__name__)


class RedditClient:
    """Wrapper for Reddit research (PRAW or public JSON)."""

    def __init__(self):
        settings = get_settings()
        self.headers = {
            "User-Agent": settings.reddit_user_agent,
            "Accept": "application/json",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.base_urls = (
            "https://www.reddit.com",
            "https://old.reddit.com",
        )
        self._praw = None
        if settings.is_reddit_api_configured():
            try:
                import praw
                self._praw = praw.Reddit(
                    client_id=settings.reddit_client_id,
                    client_secret=settings.reddit_client_secret,
                    user_agent=settings.reddit_user_agent,
                )
                self._praw.read_only = True
                logger.info("Reddit client using official PRAW API")
            except Exception as exc:
                logger.warning("PRAW init failed, using public JSON: %s", exc)

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        params = dict(params or {})
        params.setdefault("raw_json", "1")
        last_error = None
        for base_url in self.base_urls:
            url = f"{base_url}{path}"
            try:
                response = self.session.get(url, params=params, timeout=15)
                if response.status_code == 403:
                    last_error = "403 forbidden"
                    continue
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as exc:
                last_error = str(exc)
            except Exception as exc:
                last_error = str(exc)
        if last_error:
            logger.error("Reddit JSON request failed for %s: %s", path, last_error)
        return None

    def _posts_from_praw(self, subreddit_name: str, limit: int, time_filter: str) -> List[Dict[str, Any]]:
        if not self._praw:
            return []
        try:
            subreddit = self._praw.subreddit(subreddit_name)
            if time_filter in {"hour", "day", "week", "month", "year", "all"}:
                submissions = subreddit.top(time_filter=time_filter, limit=limit)
            else:
                submissions = subreddit.hot(limit=limit)
            return [self._parse_post_from_submission(s) for s in submissions]
        except Exception as exc:
            logger.warning("PRAW fetch failed for r/%s: %s", subreddit_name, exc)
            return []

    def _parse_post_from_submission(self, submission) -> Dict[str, Any]:
        created = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
        title = submission.title or ""
        selftext = getattr(submission, "selftext", "") or ""
        content = title
        if selftext:
            content += f"\n\n{selftext[:500]}"
        score = submission.score or 0
        num_comments = submission.num_comments or 0
        return {
            "post_id": submission.id,
            "title": title,
            "content": content,
            "author": str(submission.author) if submission.author else "deleted",
            "subreddit": submission.subreddit.display_name,
            "url": submission.url,
            "permalink": f"https://reddit.com{submission.permalink}",
            "score": score,
            "num_comments": num_comments,
            "engagement_score": score + (num_comments * 2),
            "created_at": created,
            "is_self": submission.is_self,
        }

    def search_posts(
        self,
        query: str,
        subreddits: Optional[List[str]] = None,
        limit: int = 20,
        time_filter: str = "day",
    ) -> List[Dict[str, Any]]:
        all_posts = []
        if subreddits:
            for subreddit in subreddits:
                posts = self.get_top_posts(
                    subreddit,
                    limit=max(limit // len(subreddits) + 5, 1),
                    time_filter=time_filter,
                )
                all_posts.extend(posts)
        else:
            data = self._get_json(
                "/search.json",
                params={
                    "q": query,
                    "limit": limit,
                    "t": time_filter,
                    "sort": "top",
                },
            )
            if data:
                for child in data.get("data", {}).get("children", []):
                    all_posts.append(self._parse_post(child.get("data", {})))
        return all_posts

    @retry_transient(max_attempts=3, delay_seconds=1.5)
    def get_top_posts(
        self,
        subreddit_name: str,
        limit: int = 20,
        time_filter: str = "day",
    ) -> List[Dict[str, Any]]:
        praw_posts = self._posts_from_praw(subreddit_name, limit, time_filter)
        if praw_posts:
            return praw_posts

        paths = [
            f"/r/{subreddit_name}/top/.json",
            f"/r/{subreddit_name}/hot/.json",
            f"/r/{subreddit_name}/.json",
        ]
        for path in paths:
            params = {"limit": min(limit, 100)}
            if "top" in path:
                params["t"] = time_filter
            data = self._get_json(path, params=params)
            if not data:
                continue
            posts = []
            for child in data.get("data", {}).get("children", []):
                posts.append(self._parse_post(child.get("data", {})))
            if posts:
                return posts
        return []

    def _parse_post(self, post_data: Dict[str, Any]) -> Dict[str, Any]:
        score = post_data.get("score", 0)
        num_comments = post_data.get("num_comments", 0)
        engagement_score = score + (num_comments * 2)
        title = post_data.get("title", "")
        selftext = post_data.get("selftext", "")
        content = title
        if selftext:
            content += f"\n\n{selftext[:500]}"
        created_utc = post_data.get("created_utc", 0)
        return {
            "post_id": post_data.get("id", ""),
            "title": title,
            "content": content,
            "author": post_data.get("author", "deleted"),
            "subreddit": post_data.get("subreddit", "unknown"),
            "url": post_data.get("url", ""),
            "permalink": f"https://reddit.com{post_data.get('permalink', '')}",
            "score": score,
            "num_comments": num_comments,
            "engagement_score": engagement_score,
            "created_at": datetime.fromtimestamp(created_utc, tz=timezone.utc),
            "is_self": post_data.get("is_self", False),
        }

    def get_relevant_subreddits(self, topic: str) -> List[str]:
        subreddit_map = {
            "ai": ["artificial", "MachineLearning", "OpenAI", "ChatGPT", "singularity"],
            "crypto": ["CryptoCurrency", "Bitcoin", "ethereum", "CryptoMarkets"],
            "technology": ["technology", "tech", "gadgets", "Futurology"],
            "politics": ["politics", "worldnews", "news"],
            "business": ["business", "Economics", "stocks", "investing"],
            "science": ["science", "EverythingScience", "askscience"],
            "programming": ["programming", "coding", "learnprogramming", "webdev"],
            "gaming": ["gaming", "Games", "pcgaming"],
            "sports": ["sports", "nfl", "nba", "soccer"],
        }
        topic_lower = topic.lower()
        for key, subreddits in subreddit_map.items():
            if key in topic_lower or topic_lower in key:
                return subreddits[:3]
        return ["news", "worldnews"]
