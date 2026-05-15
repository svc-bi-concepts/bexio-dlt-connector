"""
Bexio → dlt pipeline: full extract per configured REST endpoint, load into DuckDB or Snowflake.

Flow:
  OAuth (bexio_credentials) → Bearer headers → paginated GET api.bexio.com → flatten JSON rows
  → add row_hash (business-only, for SCD2), _loaded_at, optional _extract_run_id → dlt.resource per
  endpoint with merge/scd2 → destination.

Env (see AUTHENTICATION.md for auth; README / IMPROVEMENT_PLAN for PSA):
  BEXIO_DLT_DESTINATION     duckdb | snowflake (default duckdb)
  BEXIO_DLT_DATASET_NAME    dlt dataset/schema name (default bexio)
  BEXIO_DLT_PIPELINE_NAME   dlt pipeline name; DuckDB file name (default bexio_pipeline)
  LOG_LEVEL                 logging level (default INFO)
  PIPELINE_RUN_ID / SNOWFLAKE_JOB_ID  optional lineage on each row (_extract_run_id)
  BEXIO_DATA_DIR / BEXIO_LOADER_STATE_DIR  persisted fingerprints; last_run.json + history/*.json + fingerprints/
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import dlt
import requests
from dotenv import load_dotenv

from bexio_credentials import build_headers, resolve_bearer_token
from loader_state import (
    ResourceRunAccumulator,
    atomic_write_json,
    ensure_state_layout,
    fingerprint_path,
    history_snapshot_path,
    last_run_path,
    load_fingerprint,
    state_root,
)

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# dlt PSA / SCD2
# dlt adds _dlt_valid_from / _dlt_valid_to. row_hash drives "same version vs new version":
# only when row_hash changes does SCD2 close the old row and insert a new active row.
# ---------------------------------------------------------------------------
SCD2_WRITE_DISPOSITION: Dict[str, Any] = {
    "disposition": "merge",
    "strategy": "scd2",
    "row_version_column_name": "row_hash",
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _configure_logging() -> None:
    """Idempotent basicConfig so importing this module does not reset handlers repeatedly."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=os.getenv("LOG_LEVEL", "INFO").upper(),
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )


# ---------------------------------------------------------------------------
# Errors from dlt extraction are often wrapped; unwrap to classify HTTP status.
# ---------------------------------------------------------------------------
def _root_http_error(exc: BaseException) -> Optional[requests.HTTPError]:
    """Walk __cause__ / __context__ to find a requests.HTTPError (e.g. 403, 404)."""
    seen: set[int] = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, requests.HTTPError):
            return cur
        cur = cur.__cause__ or cur.__context__
    return None


def _endpoint_http_outcome(exc: BaseException) -> Tuple[str, int]:
    """Map exception to (summary label, log level) for per-endpoint handling."""
    http_err = _root_http_error(exc)
    if http_err is not None and http_err.response is not None:
        status_code = http_err.response.status_code
        if status_code == 403:
            return "skipped_forbidden", logging.WARNING
        if status_code == 404:
            return "skipped_not_found", logging.WARNING
    return "failed", logging.ERROR


def psa_business_row_hash(row: Dict[str, Any]) -> str:
    """
    Stable hash over business columns only. Excludes PSA lineage fields so SCD2 does not
    append a new version on every load when only metadata changes.
    """
    exclude = frozenset({"_loaded_at", "_extract_run_id", "row_hash"})
    subset = {k: row[k] for k in sorted(row.keys()) if k not in exclude}
    canonical = json.dumps(subset, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# HTTP / API constants
# Paths are relative to BASE_URL (bexio docs). Some v4 endpoints cap limit at 500.
# ---------------------------------------------------------------------------
BASE_URL = "https://api.bexio.com/"
DEFAULT_REQUEST_LIMIT = 2000
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 3

# Map dlt resource name → bexio path (and optional per-endpoint page size).
ENDPOINTS: Dict[str, Dict[str, Any]] = {
    "contacts": {"path": "2.0/contact"},
    "invoices": {"path": "2.0/kb_invoice"},
    "accounts": {"path": "2.0/accounts"},
    "account_groups": {"path": "2.0/account_groups"},
    "payments": {"path": "3.0/banking/payments"},
    "journal": {"path": "3.0/accounting/journal"},
    "bills": {"path": "4.0/purchase/bills", "limit": 500},
    "manual_entries": {"path": "3.0/accounting/manual_entries"},
    "contact_group": {"path": "2.0/contact_group"},
    "contact_branch": {"path": "2.0/contact_branch"},
    "orders": {"path": "2.0/kb_order"},
    "contact_relation": {"path": "2.0/contact_relation"},
    "purchase_orders": {"path": "3.0/purchase_orders"},
    "salutation": {"path": "2.0/salutation"},
    "title": {"path": "2.0/title"},
    "offer": {"path": "2.0/kb_offer"},
    "delivery": {"path": "2.0/kb_delivery"},
    "expenses": {"path": "4.0/expenses", "limit": 500},
    "calendar_years": {"path": "3.0/accounting/calendar_years"},
    "business_years": {"path": "3.0/accounting/business_years"},
    "currencies": {"path": "3.0/currencies"},
    "taxes": {"path": "3.0/taxes"},
    "banking_accounts": {"path": "3.0/banking/accounts"},
    "article": {"path": "2.0/article"},
    "client_service": {"path": "2.0/client_service"},
    "communication_kind": {"path": "2.0/communication_kind"},
    "files": {"path": "3.0/files"},
    "company_profile": {"path": "2.0/company_profile"},
    "country": {"path": "2.0/country"},
    "language": {"path": "2.0/language"},
    "payment_type": {"path": "2.0/payment_type"},
    "task": {"path": "2.0/task"},
    "unit": {"path": "2.0/unit"},
    "users": {"path": "3.0/users"},
}


# ---------------------------------------------------------------------------
# Flatten nested bexio JSON into one dict per row (wide columns, good for warehouse PSA).
# Top-level "id" stays "id"; nested ids become prefixed keys so we do not collide.
# ---------------------------------------------------------------------------
def flatten_item(item: Dict[str, Any], parent_key: str = "", result: Dict[str, Any] = None) -> Dict[str, Any]:
    if result is None:
        result = {}

    for key, value in item.items():
        new_key = f"{parent_key}_{key}" if parent_key else key
        if key == "id":
            result[new_key] = value
        elif isinstance(value, dict):
            flatten_item(value, new_key, result)
        elif isinstance(value, list) and all(isinstance(elem, dict) for elem in value):
            for i, elem in enumerate(value):
                flatten_item(elem, f"{new_key}_{i}", result)
        else:
            result[new_key] = value
    return result


def flatten(data: Any) -> List[Dict[str, Any]]:
    """Normalize list or envelope { "data": [...] } into a list of flat dicts."""
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            return [flatten_item(item) for item in data["data"]]
        return [flatten_item(data)]

    if isinstance(data, list):
        return [flatten_item(item) for item in data]

    return []


def request_with_retries(
    path: str, params: Dict[str, int], headers: Dict[str, str]
) -> requests.Response:
    """GET with exponential backoff on transient request failures."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                BASE_URL + path,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            backoff = 2 ** (attempt - 1)
            logger.warning("Retrying %s (attempt %s/%s): %s", path, attempt, MAX_RETRIES, exc)
            time.sleep(backoff)
    raise RuntimeError(f"Failed request for {path}")


def grab_data(
    path: str, request_limit: int, headers: Dict[str, str]
) -> Iterable[Dict[str, Any]]:
    """Page through one bexio collection until a short page or empty response."""
    offset = 0
    while True:
        response = request_with_retries(path, {"limit": request_limit, "offset": offset}, headers)

        response_data = response.json()
        if not response_data:
            break

        rows = flatten(response_data)
        if not rows:
            break

        for row in rows:
            yield row

        # Short page ⇒ last page for this endpoint.
        if len(rows) < request_limit:
            break
        offset += request_limit


# ---------------------------------------------------------------------------
# dlt destination (DuckDB file name follows pipeline_name).
# ---------------------------------------------------------------------------
def _destination_name() -> str:
    dest = (os.getenv("BEXIO_DLT_DESTINATION") or "duckdb").strip().lower()
    if dest not in ("duckdb", "snowflake"):
        raise ValueError(
            f"BEXIO_DLT_DESTINATION must be 'duckdb' or 'snowflake', got {dest!r}. "
            "See https://dlthub.com/docs/dlt-ecosystem/destinations/snowflake for Snowflake credentials."
        )
    return dest


def run_pipeline() -> None:
    """
    Run one load: refresh OAuth token once, then each endpoint as its own dlt resource.

    SCD2 expects a stable business natural key: we use primary_key ``id`` (bexio entity id).
    403/404 on an endpoint are logged and skipped so other tables still load.
    """
    _configure_logging()
    ensure_state_layout()
    run_started_at = datetime.now(timezone.utc).isoformat()
    access_token = resolve_bearer_token()
    headers = build_headers(access_token)
    extract_run_id = os.getenv("PIPELINE_RUN_ID") or os.getenv("SNOWFLAKE_JOB_ID") or ""
    # Same timestamp for all rows in this run (PSA batch marker).
    loaded_at = datetime.now(timezone.utc).isoformat()

    destination = _destination_name()
    dataset_name = (os.getenv("BEXIO_DLT_DATASET_NAME") or "bexio").strip()
    pipeline_name = (os.getenv("BEXIO_DLT_PIPELINE_NAME") or "bexio_pipeline").strip()

    logger.info(
        "Starting pipeline name=%r destination=%r dataset=%r (PSA SCD2 merge: new row only when "
        "business row_hash changes; metadata _loaded_at / _extract_run_id excluded from hash)",
        pipeline_name,
        destination,
        dataset_name,
    )

    pipeline = dlt.pipeline(
        pipeline_name=pipeline_name,
        destination=destination,
        dataset_name=dataset_name,
    )

    def build_rows(
        endpoint_path: str,
        endpoint_limit: int,
        accumulator: ResourceRunAccumulator,
    ):
        def endpoint_rows():
            for row in grab_data(endpoint_path, endpoint_limit, headers):
                enriched = dict(row)
                # Hash before _loaded_at so lineage is excluded from SCD2 version comparison.
                enriched["row_hash"] = psa_business_row_hash(enriched)
                enriched["_loaded_at"] = loaded_at
                if extract_run_id:
                    enriched["_extract_run_id"] = extract_run_id
                accumulator.observe_row(enriched.get("id"), enriched["row_hash"])
                yield enriched

        return endpoint_rows

    results: Dict[str, str] = {}
    table_stats: Dict[str, Any] = {}
    for name, endpoint in ENDPOINTS.items():
        endpoint_path = endpoint["path"]
        endpoint_limit = endpoint.get("limit", DEFAULT_REQUEST_LIMIT)
        fp_path = fingerprint_path(name)
        accumulator = ResourceRunAccumulator(
            resource_name=name,
            prev_fingerprint=load_fingerprint(fp_path),
        )
        try:
            endpoint_resource = dlt.resource(
                build_rows(endpoint_path, endpoint_limit, accumulator),
                name=name,
                write_disposition=SCD2_WRITE_DISPOSITION,
                primary_key="id",
            )
            info = pipeline.run(endpoint_resource, table_name=name)
            atomic_write_json(fp_path, accumulator.current_fingerprint)
            extracted_total = sum(accumulator.counts.values())
            table_stats[name] = {
                "status": "ok",
                "extracted_rows": extracted_total,
                "rows_new": accumulator.counts["new"],
                "rows_updated": accumulator.counts["updated"],
                "rows_unchanged": accumulator.counts["unchanged"],
                "rows_without_id": accumulator.counts["no_id"],
                "dlt_load_ids": list(info.loads_ids),
            }
            logger.info(
                "Loaded endpoint %r: %s | change_counts=%s",
                name,
                info,
                {k: v for k, v in accumulator.counts.items() if v},
            )
            results[name] = "ok"
        except Exception as exc:
            outcome, level = _endpoint_http_outcome(exc)
            if outcome == "skipped_forbidden":
                results[name] = outcome
                table_stats[name] = {"status": outcome}
                logger.log(
                    level,
                    (
                        "Skipping endpoint %r (path=%s): HTTP 403 Forbidden. "
                        "This is expected if the module is not in your bexio plan, the OAuth token "
                        "lacks scope, or the connecting user has no right to this resource. "
                        "Pipeline continues with other endpoints."
                    ),
                    name,
                    endpoint_path,
                )
            elif outcome == "skipped_not_found":
                results[name] = outcome
                table_stats[name] = {"status": outcome}
                logger.log(
                    level,
                    "Skipping endpoint %r (path=%s): HTTP 404 Not Found.",
                    name,
                    endpoint_path,
                )
            else:
                results[name] = f"failed: {exc}"
                table_stats[name] = {"status": "failed", "error": str(exc)}
                logger.error(
                    "Endpoint %r (path=%s) failed: %s",
                    name,
                    endpoint_path,
                    exc,
                    exc_info=True,
                )

    aggregate_keys = (
        "extracted_rows",
        "rows_new",
        "rows_updated",
        "rows_unchanged",
        "rows_without_id",
    )
    aggregate = {k: 0 for k in aggregate_keys}
    for stats in table_stats.values():
        if stats.get("status") != "ok":
            continue
        for k in aggregate_keys:
            aggregate[k] += int(stats.get(k, 0))

    finished_at = datetime.now(timezone.utc)
    finished_iso = finished_at.isoformat()
    last_run_doc = {
        "schema_version": 1,
        "pipeline_name": pipeline_name,
        "destination": destination,
        "dataset_name": dataset_name,
        "pipeline_run_id": extract_run_id,
        "started_at": run_started_at,
        "finished_at": finished_iso,
        "state_dir": str(state_root()),
        "aggregate": aggregate,
        "tables": table_stats,
    }
    atomic_write_json(last_run_path(), last_run_doc)
    hist_path = history_snapshot_path(finished_at, extract_run_id)
    atomic_write_json(hist_path, last_run_doc)
    logger.info("Loader state latest=%s history=%s", last_run_path(), hist_path)

    logger.info("Endpoint run summary:")
    for endpoint_name, status in results.items():
        logger.info("- %s: %s", endpoint_name, status)


if __name__ == "__main__":
    run_pipeline()
