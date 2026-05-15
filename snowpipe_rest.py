"""Snowpipe REST insertFiles helper."""

from __future__ import annotations

import logging
import os
import urllib.parse
import uuid

import requests

from snowflake_jwt import generate_jwt, jwt_headers, snowflake_rest_host

logger = logging.getLogger(__name__)


def insert_files(
    *,
    pipe_fqn: str,
    relative_paths: list[str],
    account_identifier: str,
    username: str,
    private_key_pem: bytes,
    private_key_passphrase: bytes | None = None,
) -> dict:
    """
    Queue staged files on Snowpipe.

    relative_paths are paths relative to the stage root (as returned by PUT / stage volume).

    https://docs.snowflake.com/en/user-guide/data-load-snowpipe-rest-apis
    """
    host = snowflake_rest_host(account_identifier)
    pipe_encoded = urllib.parse.quote(pipe_fqn.upper(), safe="")
    url = f"https://{host}/v1/data/pipes/{pipe_encoded}/insertFiles"
    req_id = str(uuid.uuid4())
    params = {"requestId": req_id}

    token = generate_jwt(
        account_identifier=account_identifier,
        username=username,
        private_key_pem=private_key_pem,
        private_key_passphrase=private_key_passphrase,
    )
    headers = jwt_headers(token)

    body = {"files": [{"path": p} for p in relative_paths]}
    r = requests.post(url, headers=headers, params=params, json=body, timeout=120)
    if not r.ok:
        logger.error("insertFiles failed %s %s", r.status_code, r.text[:2000])
    r.raise_for_status()
    return r.json()


def load_private_key_from_env() -> tuple[bytes, bytes | None]:
    pem_raw = os.getenv("SNOWPIPE_PRIVATE_KEY_PEM") or os.getenv("SNOWPIPE_RSA_PRIVATE_KEY_PEM") or ""
    pem_raw = pem_raw.strip()
    if pem_raw.startswith('"') and pem_raw.endswith('"'):
        pem_raw = pem_raw[1:-1]
    pem_raw = pem_raw.replace("\\n", "\n")
    if not pem_raw:
        raise RuntimeError(
            "Set SNOWPIPE_PRIVATE_KEY_PEM to PEM text (with \\n escapes), "
            "or mount a file and read before export."
        )
    passphrase = (os.getenv("SNOWPIPE_PRIVATE_KEY_PASSPHRASE") or "").encode()
    passphrase_val: bytes | None = passphrase if passphrase else None
    return pem_raw.encode("utf-8"), passphrase_val
