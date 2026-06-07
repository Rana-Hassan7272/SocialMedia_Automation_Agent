"""
Twitter/X API client wrapper.
Supports per-user OAuth 2.0 tokens and legacy single-account .env credentials.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import tweepy

from ..config import get_settings
from .logging_config import get_logger

if TYPE_CHECKING:
    from ..database.db_manager import DatabaseManager
from .retry import retry_transient

logger = get_logger(__name__)


class TwitterClient:
    """Wrapper for Twitter/X API using Tweepy."""

    def __init__(
        self,
        access_token: str,
        x_username: Optional[str] = None,
        refresh_token: Optional[str] = None,
        access_token_secret: Optional[str] = None,
    ):
        settings = get_settings()
        client_id = settings.twitter_client_id or settings.twitter_api_key
        client_secret = settings.twitter_client_secret or settings.twitter_api_secret
        if not client_id or not client_secret:
            raise ValueError("X API client credentials are not configured")

        self.access_token = access_token
        self.refresh_token = refresh_token
        self.x_username = x_username
        client_kwargs = {
            "consumer_key": client_id,
            "consumer_secret": client_secret,
            "access_token": access_token,
            "wait_on_rate_limit": True,
        }
        if access_token_secret:
            client_kwargs["access_token_secret"] = access_token_secret
        self.client = tweepy.Client(**client_kwargs)

    @classmethod
    def from_user_id(cls, user_id: int, db_manager: "DatabaseManager") -> "TwitterClient":
        from ..auth.token_refresh import ensure_fresh_access_token
        access_token = ensure_fresh_access_token(user_id, db_manager)
        token_data = db_manager.get_user_oauth_tokens(user_id)
        if not token_data:
            raise ValueError("Connect your X account before publishing")
        return cls(
            access_token=access_token,
            refresh_token=token_data.get("refresh_token"),
            x_username=token_data.get("x_username"),
        )

    @classmethod
    def from_legacy_env(cls) -> "TwitterClient":
        settings = get_settings()
        if not settings.is_twitter_configured():
            raise ValueError("Twitter API credentials not configured in .env file")
        return cls(
            access_token=settings.twitter_access_token,
            access_token_secret=settings.twitter_access_token_secret,
            x_username=None,
        )

    @retry_transient(max_attempts=3, delay_seconds=2.0)
    def create_tweet(self, text: str) -> Dict[str, str]:
        logger.info("Publishing tweet as @%s", self.x_username or "unknown")
        response = self.client.create_tweet(text=text)
        tweet_id = str(response.data["id"])
        username = self.x_username or "i"
        return {
            "tweet_id": tweet_id,
            "tweet_url": f"https://twitter.com/{username}/status/{tweet_id}",
        }

    def search_tweets(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        try:
            response = self.client.search_recent_tweets(
                query=query,
                max_results=min(max_results, 100),
                tweet_fields=["created_at", "public_metrics", "author_id"],
                user_fields=["username", "name"],
                expansions=["author_id"],
            )

            if not response.data:
                return []

            users = {}
            if response.includes and "users" in response.includes:
                users = {user.id: user for user in response.includes["users"]}

            tweets = []
            for tweet in response.data:
                author = users.get(tweet.author_id)
                tweets.append({
                    "tweet_id": str(tweet.id),
                    "content": tweet.text,
                    "author": author.name if author else "Unknown",
                    "author_username": author.username if author else "unknown",
                    "created_at": tweet.created_at,
                    "likes": tweet.public_metrics["like_count"],
                    "retweets": tweet.public_metrics["retweet_count"],
                    "replies": tweet.public_metrics["reply_count"],
                    "engagement_score": (
                        tweet.public_metrics["like_count"]
                        + tweet.public_metrics["retweet_count"] * 2
                        + tweet.public_metrics["reply_count"]
                    ),
                })
            return tweets

        except tweepy.TweepyException as e:
            raise RuntimeError(f"Twitter API error: {str(e)}") from e

    def is_configured(self) -> bool:
        return bool(self.access_token)
