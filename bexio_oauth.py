"""
Bexio OpenID Connect / OAuth2 helpers (authorization code + refresh token).

Token endpoint: https://auth.bexio.com/realms/bexio/protocol/openid-connect/token
"""

from __future__ import annotations

import logging
import os
import secrets
import tempfile
from typing import Any, Dict, Tuple
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_URL = (
    "https://auth.bexio.com/realms/bexio/protocol/openid-connect/token"
)
DEFAULT_AUTH_URL = (
    "https://auth.bexio.com/realms/bexio/protocol/openid-connect/auth"
)


def token_url() -> str:
    return os.getenv("BEXIO_TOKEN_URL", DEFAULT_TOKEN_URL)


def authorization_url() -> str:
    return os.getenv("BEXIO_AUTHORIZATION_URL", DEFAULT_AUTH_URL)


def exchange_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    r = requests.post(
        token_url(),
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> Dict[str, Any]:
    r = requests.post(
        token_url(),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def build_authorization_redirect(
    *,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str | None = None,
) -> Tuple[str, str]:
    state = state or secrets.token_urlsafe(16)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    }
    return f"{authorization_url()}?{urlencode(params)}", state


def load_refresh_token_from_env_or_file() -> str | None:
    """
    Refresh token: prefer BEXIO_REFRESH_TOKEN_FILE when present so IdP-rotated
    tokens on disk beat a stale BEXIO_REFRESH_TOKEN in the environment.
    """
    path = (os.getenv("BEXIO_REFRESH_TOKEN_FILE") or "").strip()
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            file_tok = f.read().strip()
        if file_tok:
            return file_tok
    env_tok = (os.getenv("BEXIO_REFRESH_TOKEN") or "").strip()
    if env_tok:
        return env_tok
    return None


def persist_refresh_token_if_configured(new_refresh_token: str, previous: str) -> None:
    """When IdP returns a new refresh token, persist it for the next run (no manual .env edit)."""
    if not new_refresh_token or new_refresh_token == previous:
        return
    path = (os.getenv("BEXIO_REFRESH_TOKEN_FILE") or "").strip()
    if not path:
        logger.info(
            "Refresh token was rotated by the IdP. Set BEXIO_REFRESH_TOKEN_FILE to a writable path "
            "so the new token is persisted automatically for the next container run."
        )
        return
    parent = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".bexio_refresh.", dir=parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_refresh_token)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    logger.info("Persisted rotated Bexio refresh token to %s", path)
