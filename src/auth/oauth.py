import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests
from requests.auth import HTTPBasicAuth

from ..config import get_settings

OAUTH_SCOPES = ["tweet.read", "tweet.write", "users.read", "offline.access"]
X_AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
X_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
OAUTH_STATE_TTL_SECONDS = 900


def _signing_key() -> bytes:
    return get_settings().require_encryption_key().encode()


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(48)


def _code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def resolve_redirect_uri(override: Optional[str] = None) -> str:
    if override:
        return override.strip()
    return get_settings().twitter_callback_url.strip()


def pack_oauth_state(code_verifier: str, redirect_uri: str) -> str:
    payload = {
        "v": code_verifier,
        "r": redirect_uri.strip(),
        "exp": int(time.time()) + OAUTH_STATE_TTL_SECONDS,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_signing_key(), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + b"." + sig).decode("ascii").rstrip("=")


def unpack_oauth_state(state: str) -> Dict[str, str]:
    try:
        padded = state + "=" * (-len(state) % 4)
        blob = base64.urlsafe_b64decode(padded.encode("ascii"))
        raw, sig = blob.rsplit(b".", 1)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid OAuth state") from exc
    expected = hmac.new(_signing_key(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid OAuth state signature")
    payload = json.loads(raw.decode("utf-8"))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("OAuth session expired. Click Authorize again.")
    verifier = payload.get("v")
    redirect = payload.get("r")
    if not verifier or not redirect:
        raise ValueError("Invalid OAuth state payload")
    return {"code_verifier": verifier, "redirect_uri": redirect}


def build_authorization_url(state: str, code_verifier: str, redirect_uri: str) -> str:
    settings = get_settings()
    settings.require_oauth()
    client_id = settings.twitter_client_id.strip()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(OAUTH_SCOPES),
        "state": state,
        "code_challenge": _code_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{X_AUTHORIZE_URL}?{urlencode(params)}"


def start_oauth_flow(redirect_uri: Optional[str] = None) -> str:
    callback = resolve_redirect_uri(redirect_uri)
    code_verifier = generate_code_verifier()
    state = pack_oauth_state(code_verifier, callback)
    return build_authorization_url(state, code_verifier, callback)


def _token_exchange_once(
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    settings = get_settings()
    client_id = settings.twitter_client_id.strip()
    client_secret = settings.twitter_client_secret.strip()
    resp = requests.post(
        X_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "client_id": client_id,
        },
        auth=HTTPBasicAuth(client_id, client_secret),
        timeout=30,
    )
    if resp.status_code != 200:
        raise ValueError(f"X token exchange failed ({resp.status_code}): {resp.text}")
    return resp.json()


def exchange_code_for_token(
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    candidates = []
    for uri in (redirect_uri, redirect_uri.rstrip("/"), f"{redirect_uri.rstrip('/')}/"):
        if uri not in candidates:
            candidates.append(uri)
    last_error = None
    for uri in candidates:
        try:
            return _token_exchange_once(code, code_verifier, uri)
        except ValueError as exc:
            last_error = exc
            if "redirect uri did not match" not in str(exc).lower():
                raise
    if last_error:
        raise last_error
    raise ValueError("X token exchange failed")


def fetch_x_user_profile(access_token: str) -> Dict[str, str]:
    resp = requests.get(
        "https://api.twitter.com/2/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"user.fields": "username"},
        timeout=30,
    )
    if resp.status_code != 200:
        raise ValueError(f"Could not fetch X profile ({resp.status_code}): {resp.text}")
    data = resp.json().get("data")
    if not data:
        raise ValueError("Could not fetch X user profile")
    return {
        "x_user_id": str(data["id"]),
        "x_username": data["username"],
    }


def probe_authorize_url(redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    callback = resolve_redirect_uri(redirect_uri)
    auth_url = start_oauth_flow(redirect_uri=callback)
    resp = requests.get(auth_url, allow_redirects=False, timeout=20)
    return {
        "authorize_url": auth_url,
        "redirect_uri": callback,
        "http_status": resp.status_code,
        "location": resp.headers.get("Location", ""),
    }


def token_expires_at(expires_in: Optional[int]) -> Optional[datetime]:
    if not expires_in:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
