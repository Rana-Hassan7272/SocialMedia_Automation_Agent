import sys

from src.config import get_settings
from src.database import DatabaseManager
from src.utils.logging_config import setup_logging


def _ok(label: str) -> None:
    print(f"  OK   {label}")


def _fail(label: str, detail: str = "") -> None:
    msg = f"  FAIL {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def _warn(label: str) -> None:
    print(f"  WARN {label}")


def check_google_llm(settings) -> bool:
    print("\n1. Google Gemini (primary LLM)")
    if settings.is_google_configured():
        _ok(f"GOOGLE_API_KEY set (model={settings.google_gemini_model})")
        return True
    _fail("GOOGLE_API_KEY missing")
    return False


def check_groq_fallback(settings) -> bool:
    print("\n2. Groq (fallback LLM)")
    if settings.is_groq_configured():
        _ok(f"GROQ_API_KEY set (model={settings.groq_model})")
        return True
    _warn("GROQ_API_KEY missing — no fallback if Gemini rate-limited")
    return settings.is_google_configured()


def check_llm(settings) -> bool:
    if not settings.is_llm_configured():
        _fail("At least one LLM provider required")
        return False
    return True


def check_oauth(settings) -> bool:
    print("\n3. X OAuth 2.0 (Streamlit multi-user — optional for now)")
    oauth_ready = settings.is_oauth_configured() and bool(settings.encryption_key)
    if settings.twitter_client_id and settings.twitter_client_secret:
        _ok("TWITTER_CLIENT_ID")
        _ok("TWITTER_CLIENT_SECRET")
    else:
        _warn("TWITTER_CLIENT_ID / TWITTER_CLIENT_SECRET missing — add later for Streamlit login")
    if settings.twitter_callback_url:
        _ok("TWITTER_CALLBACK_URL")
    if settings.encryption_key:
        _ok("ENCRYPTION_KEY")
    else:
        _fail("ENCRYPTION_KEY missing")
        return False
    if oauth_ready:
        _ok("OAuth ready for multi-user app")
    elif settings.is_twitter_configured():
        _warn("Using legacy X keys for demo/CLI until OAuth is configured")
    return True


def check_database(settings) -> bool:
    print("\n4. Database (Neon PostgreSQL)")
    url = settings.get_database_url()
    if settings.is_postgres():
        host = url.split("@")[-1] if "@" in url else url
        _ok(f"DATABASE_URL configured ({host})")
    else:
        _fail("DATABASE_URL missing — using SQLite fallback", url)
        return False
    try:
        db = DatabaseManager()
        db.initialize_database()
        _ok("Database connection and schema")
        return True
    except Exception as exc:
        _fail("Database connection", str(exc))
        return False


def check_reddit(settings) -> bool:
    print("\n5. Reddit (research API)")
    if settings.is_reddit_api_configured():
        _ok("REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET (official API)")
    else:
        _warn("REDDIT_CLIENT_ID/SECRET missing — add free keys from reddit.com/prefs/apps if JSON fails")
    try:
        from src.utils.reddit_client import RedditClient
        client = RedditClient()
        test_subs = ["news", "worldnews", "technology", "AskReddit"]
        for sub in test_subs:
            posts = client.get_top_posts(sub, limit=1, time_filter="day")
            if posts:
                _ok(f"Reddit reachable via r/{sub} ({len(posts)} sample post)")
                return True
        if settings.is_reddit_api_configured():
            _fail(
                "Reddit API",
                "credentials set but no posts returned — check REDDIT_USER_AGENT and app type (script)",
            )
            return False
        _warn("Reddit live test skipped — add REDDIT_CLIENT_ID/SECRET from reddit.com/prefs/apps for research")
        return True
    except Exception as exc:
        _fail("Reddit API", str(exc))
        return False


def check_legacy_twitter(settings) -> bool:
    print("\n6. Legacy X keys (demo / your-account publish)")
    if settings.is_twitter_configured():
        _ok("OAuth 1.0a legacy keys present")
        return True
    _warn("Legacy X keys not set")
    return True


def main() -> int:
    setup_logging()
    settings = get_settings()
    print("SocialPulse setup verification")
    print("=" * 60)

    required = [
        check_google_llm(settings),
        check_groq_fallback(settings),
        check_llm(settings),
        check_database(settings),
        check_reddit(settings),
    ]
    optional = [
        check_oauth(settings),
        check_legacy_twitter(settings),
    ]

    print("\n" + "=" * 60)
    if all(required) and all(optional):
        print("All checks passed.")
        print("Run app: python main.py")
        print("Demo publish (your account): python demo_complete_pipeline.py")
        return 0
    if all(required):
        print("Required checks passed. Optional warnings above are OK for local demo.")
        print("Run app: python main.py")
        return 0
    print("Required checks failed. Fix issues above, then rerun:")
    print("  python main.py verify")
    return 1


if __name__ == "__main__":
    sys.exit(main())
