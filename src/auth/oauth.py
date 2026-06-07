import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests
import tweepy
from requests.auth import HTTPBasicAuth

from ..config import get_settings

OAUTH_SCOPES = ["tweet.read", "tweet.write", "users.read", "offline.access"]
X_AUTHORIZE_URL = "https://twitter.com/i/oauth2/authorize"
X_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def resolve_redirect_uri(override: Optional[str] = None) -> str:
    if override:
        return override.strip().rstrip("/")
    return get_settings().twitter_callback_url.rstrip("/")


def build_authorization_url(
    state: str,
    code_verifier: str,
    redirect_uri: Optional[str] = None,
) -> str:
    settings = get_settings()
    settings.require_oauth()
    client_id = settings.twitter_client_id.strip()
    callback = resolve_redirect_uri(redirect_uri)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": callback,
        "scope": " ".join(OAUTH_SCOPES),
        "state": state,
        "code_challenge": _code_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{X_AUTHORIZE_URL}?{urlencode(params)}"


def start_oauth_flow(redirect_uri: Optional[str] = None) -> Tuple[str, str, str]:
    state = generate_oauth_state()
    code_verifier = generate_code_verifier()
    auth_url = build_authorization_url(state, code_verifier, redirect_uri=redirect_uri)
    return auth_url, state, code_verifier


def exchange_code_for_token(
    code: str,
    code_verifier: str,
    state: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> Dict[str, Any]:
    settings = get_settings()
    settings.require_oauth()
    client_id = settings.twitter_client_id.strip()
    client_secret = settings.twitter_client_secret.strip()
    callback = resolve_redirect_uri(redirect_uri)
    resp = requests.post(
        X_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback,
            "code_verifier": code_verifier,
            "client_id": client_id,
        },
        auth=HTTPBasicAuth(client_id, client_secret),
        timeout=30,
    )
    if resp.status_code != 200:
        raise ValueError(f"X token exchange failed ({resp.status_code}): {resp.text}")
    return resp.json()


def fetch_x_user_profile(access_token: str) -> Dict[str, str]:
    client = tweepy.Client(access_token=access_token)
    me = client.get_me(user_fields=["username"])
    if not me.data:
        raise ValueError("Could not fetch X user profile")
    return {
        "x_user_id": str(me.data.id),
        "x_username": me.data.username,
    }


def token_expires_at(expires_in: Optional[int]) -> Optional[datetime]:
    if not expires_in:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
