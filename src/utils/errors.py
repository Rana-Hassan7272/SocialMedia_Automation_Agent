from typing import Optional


class AppError(Exception):
    def __init__(self, user_message: str, code: str = "app_error", cause: Optional[Exception] = None):
        self.user_message = user_message
        self.code = code
        self.cause = cause
        super().__init__(user_message)


class ValidationError(AppError):
    def __init__(self, user_message: str, cause: Optional[Exception] = None):
        super().__init__(user_message, code="validation_error", cause=cause)


class RateLimitError(AppError):
    def __init__(self, user_message: str, cause: Optional[Exception] = None):
        super().__init__(user_message, code="rate_limit", cause=cause)


class OAuthError(AppError):
    def __init__(self, user_message: str, cause: Optional[Exception] = None):
        super().__init__(user_message, code="oauth_error", cause=cause)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.user_message
    text = str(exc)
    text_lower = text.lower()
    if "rate limit" in text_lower or "429" in text_lower:
        return "Service is busy. Please wait a minute and try again."
    if "timeout" in text_lower or "connection" in text_lower:
        return "Network error. Check your connection and try again."
    if any(token in text_lower for token in ("groq", "gemini", "google", "api key", "llm")):
        return "AI service is unavailable. Contact the app administrator."
    if "token exchange failed" in text_lower or "authorization failed" in text_lower:
        return text
    if "oauth session not found" in text_lower:
        return text
    if "connect your x account" in text_lower:
        return text
    if "session expired" in text_lower and "disconnect" in text_lower:
        return text
    return text if len(text) < 300 else "Something went wrong. Please try again."
