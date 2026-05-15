"""JWT for Snowflake REST APIs (Snowpipe insertFiles, SQL API) — key-pair auth."""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization


def _normalize_account(account: str) -> str:
    """
    Match Snowflake SQL API docs:
    exclude region/cloud suffix after first '.' unless '.global' is present.

    Do not truncate on hyphen — account identifiers often look like ORG-ACCOUNT.
    """
    account = account.strip()
    if ".global" not in account.lower():
        idx = account.find(".")
        if idx > 0:
            account = account[0:idx]
    return account.upper()


def _public_key_fingerprint_sha256(private_key_pem: bytes, passphrase: bytes | None) -> str:
    pk = serialization.load_pem_private_key(private_key_pem, passphrase, default_backend())
    pub_der = pk.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(pub_der).digest()
    return "SHA256:" + base64.b64encode(digest).decode("utf-8")


def generate_jwt(
    *,
    account_identifier: str,
    username: str,
    private_key_pem: bytes,
    private_key_passphrase: bytes | None = None,
    lifetime_minutes: int = 59,
) -> str:
    """
    Key-pair JWT per Snowflake SQL API key-pair authentication.

    https://docs.snowflake.com/en/developer-guide/sql-api/authenticating#label-sql-api-authenticating-key-pair
    """
    account = _normalize_account(account_identifier).replace(".", "-")
    user = username.strip().upper()
    qualified = f"{account}.{user}"
    fp = _public_key_fingerprint_sha256(private_key_pem, private_key_passphrase)

    pk = serialization.load_pem_private_key(private_key_pem, private_key_passphrase, default_backend())

    now = datetime.now(timezone.utc)
    lifetime = timedelta(minutes=min(lifetime_minutes, 59))
    payload: dict[str, Any] = {
        "iss": f"{qualified}.{fp}",
        "sub": qualified,
        "iat": now,
        "exp": now + lifetime,
    }
    token = jwt.encode(payload, pk, algorithm="RS256")
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return token


def jwt_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
    }


def snowflake_rest_host(account_identifier: str) -> str:
    """
    REST hostname for Snowpipe / SQL API (same pattern many Snowflake REST clients use).

    Prefer SNOWFLAKE_HOST env if set (full hostname); else derive from account identifier.
    """
    explicit = (os.getenv("SNOWFLAKE_HOST") or "").strip().lower().replace("https://", "").split("/")[0]
    if explicit:
        return explicit
    acct = account_identifier.strip().lower()
    return f"{acct}.snowflakecomputing.com".replace("_", "-")
