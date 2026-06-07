import re
from typing import Optional

from .errors import ValidationError

MAX_QUERY_LENGTH = 500
BLOCKED_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions",
    r"disregard\s+(all\s+)?(previous|above|prior)\s+instructions",
    r"you\s+are\s+now\s+",
    r"system\s+prompt",
    r"<\s*script",
    r"javascript:",
]


def sanitize_user_query(query: str) -> str:
    cleaned = (query or "").strip()
    if not cleaned:
        raise ValidationError("Please enter a topic or question.")
    if len(cleaned) > MAX_QUERY_LENGTH:
        raise ValidationError(f"Query must be {MAX_QUERY_LENGTH} characters or fewer.")
    lowered = cleaned.lower()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            raise ValidationError("Query contains unsupported content. Please rephrase.")
    return cleaned


def sanitize_feedback(text: str, field_name: str = "Feedback") -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValidationError(f"{field_name} cannot be empty.")
    if len(cleaned) > 1000:
        raise ValidationError(f"{field_name} must be 1000 characters or fewer.")
    return cleaned
