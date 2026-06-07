from typing import Any, List, Optional

from langchain_core.messages import BaseMessage
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI

from ..config import get_settings
from .logging_config import get_logger
from .retry import retry_transient

logger = get_logger(__name__)

FALLBACK_ERROR_TOKENS = (
    "429",
    "quota",
    "rate limit",
    "rate_limit",
    "resource exhausted",
    "resource_exhausted",
    "too many requests",
    "limit reached",
    "exceeded",
    "capacity",
    "overloaded",
    "unavailable",
)


def should_fallback_to_groq(exc: BaseException) -> bool:
    text = str(exc).lower()
    exc_name = exc.__class__.__name__.lower()
    if any(token in text for token in FALLBACK_ERROR_TOKENS):
        return True
    if any(token in exc_name for token in ("ratelimit", "resourceexhausted", "quota")):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in (429, 503):
        return True
    return False


class FallbackChatModel:
    """Google Gemini primary with Groq fallback on quota/rate-limit failures."""

    def __init__(
        self,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        groq_model: Optional[str] = None,
        google_model: Optional[str] = None,
    ):
        settings = get_settings()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.google_model = google_model or settings.google_gemini_model
        self.groq_model = groq_model or settings.groq_model
        self._google_llm = None
        self._groq_llm = None

        if settings.is_google_configured():
            kwargs = {
                "model": self.google_model,
                "google_api_key": settings.google_api_key,
                "temperature": self.temperature,
            }
            if max_tokens is not None:
                kwargs["max_output_tokens"] = max_tokens
            self._google_llm = ChatGoogleGenerativeAI(**kwargs)

        if settings.is_groq_configured():
            self._groq_llm = ChatGroq(
                api_key=settings.groq_api_key,
                model=self.groq_model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

        if not self._google_llm and not self._groq_llm:
            raise ValueError(
                "No LLM configured. Set GOOGLE_API_KEY (primary) and/or GROQ_API_KEY (fallback)."
            )

    @property
    def model_label(self) -> str:
        if self._google_llm:
            return f"google:{self.google_model}"
        return f"groq:{self.groq_model}"

    @retry_transient(max_attempts=2, delay_seconds=1.0)
    def _invoke_google(self, messages: List[BaseMessage]) -> Any:
        if not self._google_llm:
            raise RuntimeError("Google Gemini is not configured")
        return self._google_llm.invoke(messages)

    @retry_transient(max_attempts=2, delay_seconds=1.0)
    def _invoke_groq(self, messages: List[BaseMessage]) -> Any:
        if not self._groq_llm:
            raise RuntimeError("Groq fallback is not configured")
        return self._groq_llm.invoke(messages)

    def invoke(self, messages: List[BaseMessage]) -> Any:
        if self._google_llm:
            try:
                logger.debug("Invoking primary LLM google:%s", self.google_model)
                return self._invoke_google(messages)
            except Exception as exc:
                if self._groq_llm and should_fallback_to_groq(exc):
                    logger.warning(
                        "Google Gemini failed (%s). Falling back to Groq model=%s",
                        exc,
                        self.groq_model,
                    )
                    return self._invoke_groq(messages)
                logger.error("Google Gemini failed without fallback: %s", exc)
                raise

        logger.debug("Invoking Groq model=%s", self.groq_model)
        return self._invoke_groq(messages)
