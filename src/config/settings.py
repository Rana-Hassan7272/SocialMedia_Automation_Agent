"""
Configuration management for Social Media Automation System.
Uses environment variables with Pydantic validation.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field, field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    google_api_key: Optional[str] = Field(None, description="Google Gemini API key (primary LLM)")
    google_gemini_model: str = Field(
        default="gemini-3.1-flash-lite",
        description="Google Gemini model name",
    )

    groq_api_key: Optional[str] = Field(None, description="Groq API key (fallback LLM)")
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model to use when Gemini fails",
    )

    twitter_client_id: Optional[str] = Field(
        None, description="X OAuth 2.0 Client ID"
    )
    twitter_client_secret: Optional[str] = Field(
        None, description="X OAuth 2.0 Client Secret"
    )
    twitter_callback_url: str = Field(
        default="http://localhost:8501",
        description="OAuth callback URL (must match X developer portal)",
    )

    twitter_api_key: Optional[str] = Field(None, description="Legacy OAuth 1.0a API key")
    twitter_api_secret: Optional[str] = Field(None, description="Legacy OAuth 1.0a API secret")
    twitter_access_token: Optional[str] = Field(None, description="Legacy access token")
    twitter_access_token_secret: Optional[str] = Field(
        None, description="Legacy access token secret"
    )
    twitter_api_version: str = Field(default="v2", description="Twitter API version")

    encryption_key: Optional[str] = Field(
        None, description="Fernet key for encrypting OAuth tokens at rest"
    )

    database_url: Optional[str] = Field(
        None,
        description="Neon/Postgres connection URL (postgresql://...)",
    )
    database_path: str = Field(
        default="data/social_automation.db",
        description="SQLite path when DATABASE_URL is not set",
    )

    log_level: str = Field(default="INFO", description="Logging level")
    max_tweets_per_query: int = Field(
        default=50,
        description="Maximum tweets to retrieve per query",
    )
    min_engagement_score: int = Field(
        default=10,
        description="Minimum engagement score for filtering",
    )
    top_tweets_count: int = Field(
        default=8,
        description="Number of top tweets for summarization",
    )
    max_workflows_per_user_per_day: int = Field(
        default=20,
        description="Daily workflow limit per user",
    )
    max_llm_calls_per_user_per_day: int = Field(
        default=50,
        description="Daily LLM call limit per user",
        validation_alias=AliasChoices(
            "MAX_LLM_CALLS_PER_USER_PER_DAY",
            "MAX_GROQ_CALLS_PER_USER_PER_DAY",
        ),
    )
    max_publish_per_user_per_day: int = Field(
        default=10,
        description="Daily publish limit per user",
    )
    reddit_user_agent: str = Field(
        default="windows:SocialPulse:v1.0 (by /u/socialpulse_bot)",
        description="Reddit API User-Agent (must be unique per Reddit rules)",
    )
    reddit_client_id: Optional[str] = Field(
        None,
        description="Reddit script app client ID (free, from reddit.com/prefs/apps)",
    )
    reddit_client_secret: Optional[str] = Field(
        None,
        description="Reddit script app secret",
    )

    def is_reddit_api_configured(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret)

    @field_validator("twitter_client_id", "twitter_client_secret", mode="before")
    @classmethod
    def strip_oauth_secrets(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1].strip()
            return v or None
        return v

    @field_validator("twitter_callback_url", mode="before")
    @classmethod
    def normalize_callback_url(cls, v: Optional[str]) -> str:
        if not v:
            return "http://localhost:8501"
        return str(v).strip().rstrip("/")

    @field_validator("database_path")
    @classmethod
    def create_data_directory(cls, v: str) -> str:
        db_path = Path(v)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v_upper

    def get_database_url(self) -> str:
        if self.database_url:
            url = self.database_url.strip()
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            if url.startswith("postgresql://") and "+psycopg" not in url:
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            return url
        return f"sqlite:///{self.database_path}"

    def is_postgres(self) -> bool:
        return self.get_database_url().startswith("postgresql")

    def is_oauth_configured(self) -> bool:
        return bool(self.twitter_client_id and self.twitter_client_secret)

    def is_twitter_configured(self) -> bool:
        return all([
            self.twitter_api_key,
            self.twitter_api_secret,
            self.twitter_access_token,
            self.twitter_access_token_secret,
        ])

    def is_google_configured(self) -> bool:
        return bool(self.google_api_key)

    def is_groq_configured(self) -> bool:
        return bool(self.groq_api_key)

    def is_llm_configured(self) -> bool:
        return self.is_google_configured() or self.is_groq_configured()

    def require_llm(self) -> None:
        if not self.is_llm_configured():
            raise ValueError(
                "No LLM configured. Set GOOGLE_API_KEY (primary) and/or GROQ_API_KEY (fallback)."
            )

    def require_encryption_key(self) -> str:
        if not self.encryption_key:
            raise ValueError(
                "ENCRYPTION_KEY is not configured. "
                "Run: python generate_encryption_key.py"
            )
        return self.encryption_key

    def require_oauth(self) -> None:
        if not self.is_oauth_configured():
            raise ValueError(
                "TWITTER_CLIENT_ID and TWITTER_CLIENT_SECRET are required for X login"
            )

    def require_database_url(self) -> str:
        url = self.get_database_url()
        if url.startswith("sqlite"):
            return url
        if not self.database_url:
            raise ValueError("DATABASE_URL is required for production (Neon PostgreSQL)")
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


class _SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()
