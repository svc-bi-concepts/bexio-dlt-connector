"""
Bexio → NDJSON files on internal stage → Snowpipe (serverless COPY into Snowflake tables).

No dlt / no virtual warehouse for the COPY itself — Snowflake bills Snowpipe ingest credits.

Flow:
  OAuth → paginated GET api.bexio.com → flatten rows → newline-delimited JSON envelopes on mounted stage
  → Snowpipe REST insertFiles → pipe COPY INTO ... SELECT transforms VARIANT columns.

Requires:
  - BEXIO_LOAD_MODE=snowpipe (see spcs/entrypoint.sh)
  - Stage mounted at BEXIO_STAGE_MOUNT (SPCS stage volume)
  - SNOWPIPE_PIPE_FQN (e.g. RAW.BEXIO_SPCS.BEXIO_JSON_PIPE)
  - Key-pair user SNOWPIPE_USER + SNOWPIPE_PRIVATE_KEY_PEM (JWT for REST)

See spcs/SNOWPIPE.md for DDL and caveats (TASK warehouse, relational modeling).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from dotenv import load_dotenv

from bexio_credentials import build_headers, resolve_bearer_token
from dlt_pipeline import (
    DEFAULT_REQUEST_LIMIT,
    ENDPOINTS,
    _configure_logging,
    _endpoint_http_outcome,
    grab_data,
    psa_business_row_hash,
)
from snowpipe_rest import insert_files, load_private_key_from_env

load_dotenv()

logger = logging.getLogger(__name__)


def run_snowpipe_export() -> Dict[str, str]:
    _configure_logging()
    stage_mount = (os.getenv("BEXIO_STAGE_MOUNT") or "/snowflake-stage").rstrip("/")
    pipe_fqn = (os.getenv("SNOWPIPE_PIPE_FQN") or "").strip()
    if not pipe_fqn:
        raise RuntimeError("Set SNOWPIPE_PIPE_FQN e.g. RAW.BEXIO_SPCS.BEXIO_JSON_PIPE")

    account_id = (os.getenv("SNOWFLAKE_ACCOUNT") or "").strip()
    snowpipe_user = (os.getenv("SNOWPIPE_USER") or "").strip()
    if not account_id or not snowpipe_user:
        raise RuntimeError("Set SNOWFLAKE_ACCOUNT and SNOWPIPE_USER for Snowpipe JWT.")

    pem, passphrase = load_private_key_from_env()

    extract_run_id = os.getenv("PIPELINE_RUN_ID") or os.getenv("SNOWFLAKE_JOB_ID") or ""
    loaded_at = datetime.now(timezone.utc).isoformat()

    os.makedirs(stage_mount, exist_ok=True)
    run_dir = os.path.join(stage_mount, extract_run_id or "run")
    os.makedirs(run_dir, exist_ok=True)

    access_token = resolve_bearer_token()
    headers = build_headers(access_token)

    results: Dict[str, str] = {}

    for name, endpoint in ENDPOINTS.items():
        endpoint_path = endpoint["path"]
        endpoint_limit = int(endpoint.get("limit", DEFAULT_REQUEST_LIMIT))
        rel_base = extract_run_id or "run"

        try:
            out_path = os.path.join(run_dir, f"{name}.ndjson")
            count = 0
            with open(out_path, "w", encoding="utf-8") as fh:
                for row in grab_data(endpoint_path, endpoint_limit, headers):
                    enriched = dict(row)
                    enriched["row_hash"] = psa_business_row_hash(enriched)
                    enriched["_loaded_at"] = loaded_at
                    if extract_run_id:
                        enriched["_extract_run_id"] = extract_run_id
                    envelope = {
                        "_extract_run_id": extract_run_id,
                        "_loaded_at": loaded_at,
                        "_resource": name,
                        "payload": enriched,
                    }
                    fh.write(json.dumps(envelope, ensure_ascii=False, default=str) + "\n")
                    count += 1

            rel_path = f"{rel_base}/{name}.ndjson"
            if count == 0:
                logger.warning("Endpoint %r produced no rows; skipping Snowpipe enqueue.", name)
                results[name] = "empty_skip"
                continue

            insert_files(
                pipe_fqn=pipe_fqn,
                relative_paths=[rel_path],
                account_identifier=account_id,
                username=snowpipe_user,
                private_key_pem=pem,
                private_key_passphrase=passphrase,
            )
            logger.info("Snowpipe queued %s (%s rows, path=%s)", name, count, rel_path)
            results[name] = "snowpipe_queued"

        except Exception as exc:
            outcome, level = _endpoint_http_outcome(exc)
            if outcome == "skipped_forbidden":
                results[name] = outcome
                logger.log(level, "Skipping endpoint %r (403)", name)
            elif outcome == "skipped_not_found":
                results[name] = outcome
                logger.log(level, "Skipping endpoint %r (404)", name)
            else:
                results[name] = f"failed: {exc}"
                logger.error("Endpoint %r failed: %s", name, exc, exc_info=True)

    logger.info("Snowpipe export summary:")
    for k, v in results.items():
        logger.info("- %s: %s", k, v)

    return results


def main() -> None:
    run_snowpipe_export()


if __name__ == "__main__":
    main()
