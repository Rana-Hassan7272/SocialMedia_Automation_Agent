from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

import requests

from ..config import get_settings
from ..utils.logging_config import get_logger
from .oauth import token_expires_at

if TYPE_CHECKING:
    from ..database.db_manager import DatabaseManager

logger = get_logger(__name__)


def _refresh_with_x(refresh_token: str) -> Dict[str, Any]:
    settings = get_settings()
    settings.require_oauth()
    response = requests.post(
        "https://api.twitter.com/2/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.twitter_client_id,
        },
        auth=(settings.twitter_client_id, settings.twitter_client_secret),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def ensure_fresh_access_token(user_id: int, db_manager: "DatabaseManager") -> str:
    token_data = db_manager.get_user_oauth_tokens(user_id)
    if not token_data:
        raise ValueError("Connect your X account before publishing")

    access_token = token_data["access_token"]
    expires_at = token_data.get("expires_at")
    refresh_token = token_data.get("refresh_token")

    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    still_valid = (
        expires_at is None
        or expires_at > datetime.now(timezone.utc)
    )
    if still_valid:
        return access_token

    if not refresh_token:
        raise ValueError("X session expired. Disconnect and connect your X account again.")

    logger.info("Refreshing expired X token for user_id=%s", user_id)
    refreshed = _refresh_with_x(refresh_token)
    new_access = refreshed["access_token"]
    new_refresh = refreshed.get("refresh_token", refresh_token)
    db_manager.save_oauth_token(
        user_id=user_id,
        access_token=new_access,
        refresh_token=new_refresh,
        expires_at=token_expires_at(refreshed.get("expires_in")),
    )
    return new_access
