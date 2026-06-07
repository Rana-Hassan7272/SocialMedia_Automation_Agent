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


def friendly_x_login_error(exc: Exception) -> str:
    text = str(exc)
    text_lower = text.lower()
    if "client-not-enrolled" in text_lower or "attached to a project" in text_lower:
        return (
            "X API access is not enabled for this account yet. "
            "SignalDraft uses pay-as-you-go X API billing — contact the administrator to activate access."
        )
    if "401" in text_lower and "unauthorized" in text_lower:
        return "X login could not be verified. Contact the administrator to enable your account."
    if "token exchange failed" in text_lower or "redirect uri" in text_lower:
        return "X login session expired. Click Connect to X and try again."
    if "oauth session expired" in text_lower or "invalid oauth state" in text_lower:
        return "Login session expired. Click Connect to X and try again."
    if len(text) > 200:
        return "X login failed. Please try again or contact the administrator."
    return text


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
        return "AI service is temporarily unavailable. Please try again shortly."
    if "connect your x account" in text_lower:
        return text
    if "session expired" in text_lower and "disconnect" in text_lower:
        return text
    return text if len(text) < 200 else "Something went wrong. Please try again."
