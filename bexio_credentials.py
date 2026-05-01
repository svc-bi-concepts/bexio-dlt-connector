"""Resolve API bearer token via OAuth (refresh grant) only — no PAT."""

from __future__ import annotations

import os

from bexio_oauth import (
    load_refresh_token_from_env_or_file,
    persist_refresh_token_if_configured,
    refresh_access_token,
)


def resolve_bearer_token() -> str:
    """
    OAuth only.

    1. BEXIO_CLIENT_ID + BEXIO_CLIENT_SECRET + refresh token (BEXIO_REFRESH_TOKEN_FILE or
       BEXIO_REFRESH_TOKEN) → refresh grant → access_token
    2. Else BEXIO_ACCESS_TOKEN if set (short-lived; debugging or emergency only)
    """
    client_id = os.getenv("BEXIO_CLIENT_ID")
    client_secret = os.getenv("BEXIO_CLIENT_SECRET")
    refresh = load_refresh_token_from_env_or_file()
    if client_id and client_secret and refresh:
        data = refresh_access_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh,
        )
        new_refresh = data.get("refresh_token") or ""
        persist_refresh_token_if_configured(new_refresh, refresh)
        access = data.get("access_token")
        if not access:
            raise RuntimeError("Token refresh response missing access_token.")
        return access

    access_only = (os.getenv("BEXIO_ACCESS_TOKEN") or "").strip()
    if access_only:
        return access_only

    raise RuntimeError(
        "OAuth only: set BEXIO_CLIENT_ID, BEXIO_CLIENT_SECRET, and BEXIO_REFRESH_TOKEN "
        "or BEXIO_REFRESH_TOKEN_FILE (see AUTHENTICATION.md and python oauth_login.py). "
        "Optional: BEXIO_ACCESS_TOKEN for a short-lived access token only."
    )


def build_headers(access_token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
