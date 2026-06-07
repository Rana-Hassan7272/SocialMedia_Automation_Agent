from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, Tuple

from ..config import get_settings
from ..database import DatabaseManager
from .errors import RateLimitError

_lock = Lock()
_memory_counts: Dict[Tuple[int, str], int] = {}


class RateLimiter:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.settings = get_settings()

    def check_workflow_limit(self, user_id: int) -> None:
        count = self.db.count_user_workflows_today(user_id)
        if count >= self.settings.max_workflows_per_user_per_day:
            raise RateLimitError("Daily workflow limit reached. Try again tomorrow.")

    def check_and_increment(self, user_id: int, bucket: str, limit: int, window_hours: int = 24) -> None:
        key = (user_id, bucket)
        with _lock:
            current = _memory_counts.get(key, 0)
            if current >= limit:
                raise RateLimitError(f"Daily {bucket} limit reached. Try again later.")
            _memory_counts[key] = current + 1

    def check_llm_limit(self, user_id: int) -> None:
        self.check_and_increment(
            user_id,
            "llm_calls",
            self.settings.max_llm_calls_per_user_per_day,
        )

    def check_publish_limit(self, user_id: int) -> None:
        self.check_and_increment(
            user_id,
            "x_publish",
            self.settings.max_publish_per_user_per_day,
        )
