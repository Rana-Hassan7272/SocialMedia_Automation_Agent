import time
from functools import wraps
from typing import Callable, Tuple, Type

from .logging_config import get_logger

logger = get_logger(__name__)

TRANSIENT_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, TRANSIENT_EXCEPTIONS):
        return True
    text = str(exc).lower()
    return any(token in text for token in ("timeout", "429", "503", "502", "rate limit", "temporarily"))


def retry_transient(max_attempts: int = 3, delay_seconds: float = 1.0):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if not is_transient(exc) or attempt >= max_attempts:
                        raise
                    wait = delay_seconds * attempt
                    logger.warning(
                        "Transient error in %s (attempt %s/%s): %s. Retrying in %ss",
                        func.__name__,
                        attempt,
                        max_attempts,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
            raise last_exc
        return wrapper
    return decorator
