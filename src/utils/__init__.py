from .reddit_client import RedditClient

__all__ = ["TwitterClient", "RedditClient"]


def __getattr__(name: str):
    if name == "TwitterClient":
        from .twitter_client import TwitterClient
        return TwitterClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
