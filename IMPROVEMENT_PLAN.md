# bexio-dlt-connector — improvement plan

This document captures agreed direction: **OAuth application auth**, **PSA-style historization metadata**, and **daily runs on Snowflake Snowpark Container Services (SPCS)**.

---

## 1. Authentication (bexio application / OIDC)

### Current state

- **OAuth only**: `BEXIO_CLIENT_ID`, `BEXIO_CLIENT_SECRET`, `BEXIO_REFRESH_TOKEN` or `BEXIO_REFRESH_TOKEN_FILE`. The pipeline refreshes at `https://auth.bexio.com/realms/bexio/protocol/openid-connect/token` before each run. Personal Access Tokens are **not** supported by this connector.
- **One-time browser login**: run `python oauth_login.py` (repo root; not required inside the slim Docker image unless you copy the script). Register the same `BEXIO_REDIRECT_URI` in the [bexio developer portal](https://developer.bexio.com). Copy the printed `BEXIO_REFRESH_TOKEN` into your secret store (never commit). Optional: `BEXIO_SCOPES` (space-separated) — see `oauth_login.py` default read scopes.
- **Shared resolver**: `bexio_credentials.resolve_bearer_token()` is used by `dlt_pipeline.py`.

### Recommended next steps

| Priority | Item | Notes |
|----------|------|--------|
| P0 | **Scopes** | Set `BEXIO_SCOPES` to the minimal API scopes your ETL needs (plus `openid`, `offline_access`). Stay least-privilege vs the default list in `oauth_login.py` where possible. |
| P0 | **Secret rotation (automatic)** | Set **`BEXIO_REFRESH_TOKEN_FILE`** to a **writable** path on a **persistent volume** (SPCS volume, K8s PVC, etc.). On each refresh, if bexio returns a new refresh token, the pipeline **atomically overwrites** that file; the next run loads the file **before** `BEXIO_REFRESH_TOKEN` env so stale injected env does not win. If the file path is unset, the app logs that rotation occurred and you must update your secret store yourself (or use an operator that syncs the file into the store). |
| P1 | **Access-token caching** | Decode JWT `exp` and skip refresh when still valid (fewer calls to auth). |

---

## 2. PSA historization (SCD2 + lineage)

### Current state

- **`write_disposition`**: dlt **`merge`** with **`strategy: scd2`** ([dlt merge / SCD2](https://dlthub.com/docs/general-usage/merge-loading#scd2-strategy)). Destination adds **`_dlt_valid_from`** / **`_dlt_valid_to`** for type-2 history; absent rows in a full extract can be retired (closed) per dlt rules.
- **`primary_key`**: `id` (bexio entity id).
- **`row_hash`**: SHA-256 of canonical JSON over **business columns only**; **`row_version_column_name`** points SCD2 at this hash so **`_loaded_at`** and **`_extract_run_id`** do **not** create a new version every run when data is unchanged.
- **`_loaded_at`**: UTC ISO-8601 on each row for batch lineage.
- **`_extract_run_id`**: from `PIPELINE_RUN_ID` or `SNOWFLAKE_JOB_ID` when set.
- **Destination**: `BEXIO_DLT_DESTINATION` — `duckdb` (default) or `snowflake` (install `dlt[duckdb,snowflake]`; configure Snowflake per [dlt Snowflake](https://dlthub.com/docs/dlt-ecosystem/destinations/snowflake)). **`BEXIO_DLT_DATASET_NAME`** (default `bexio`), **`BEXIO_DLT_PIPELINE_NAME`** (default `bexio_pipeline`, affects DuckDB file name).

### Recommended next steps

| Priority | Item | Notes |
|----------|------|--------|
| P0 | **Migrating from old `replace` loads** | Reuse the same DuckDB file + table names under a new merge strategy can conflict. Prefer a **new** `BEXIO_DLT_PIPELINE_NAME` / catalog file or **new** `BEXIO_DLT_DATASET_NAME`, or drop old tables before first SCD2 load. |
| P1 | **`_dlt_load_id`** | Use alongside `_loaded_at` for audit. |
| P1 | **Snowflake in prod** | Set `BEXIO_DLT_DESTINATION=snowflake` and wire credentials (e.g. `.dlt/secrets.toml` or your platform’s secret injection). |

---

## 3. Snowflake Snowpark Container Services (daily job)

### Target architecture (outline)

1. **Container image**: build from this repo’s `Dockerfile`; entrypoint runs `python dlt_pipeline.py` (or a thin wrapper that sets `PIPELINE_RUN_ID`).
2. **Schedule**: SPCS **service spec** or **job** triggered once per day (or Snowflake **TASK** calling `SYSTEM$START_SPCS_SERVICE` / job API per your org pattern).
3. **Secrets** (Snowflake **generic secret** or integration):
   - `BEXIO_CLIENT_ID`, `BEXIO_CLIENT_SECRET`, `BEXIO_REFRESH_TOKEN`
   - Snowflake user/password or keypair for dlt Snowflake destination
4. **Environment**: inject `PIPELINE_RUN_ID` (e.g. UUID or `CURRENT_TIMESTAMP` passed from the orchestrator), `SNOWFLAKE_JOB_ID` if available.
5. **State**: dlt pipeline state under `.dlt/` — mount a **volume** or sync to a stage if you need multi-replica semantics (single daily replica is simplest).
6. **Networking**: allow egress to `api.bexio.com` and `auth.bexio.com`.

### Recommended next steps

| Priority | Item | Notes |
|----------|------|--------|
| P0 | **Dockerfile for SPCS** | Multi-stage image, non-root user, no secrets in layers; secrets only at runtime. |
| P0 | **dlt → Snowflake** | Add `dlt[snowflake]`, configure destination in code or `secrets.toml` / env per dlt docs. |
| P1 | **Observability** | Structured logs to stdout; capture in Snowflake logging or external collector; alert on non-zero “failed” endpoints in summary. |
| P2 | **Cost** | Right-size CPU/memory; daily run is usually small; watch full-table `replace` API volume. |

---

## 4. API client robustness (already partially done)

| Priority | Item | Notes |
|----------|------|--------|
| P1 | **429 handling** | Respect `RateLimit-Reset` / backoff; distinguish 429 vs 5xx. |
| P1 | **`requests.Session`** | Connection pooling for many endpoints per run. |
| P2 | **Incremental** | Where APIs support `updated_at` / cursors, switch from full extract to incremental + `merge`. |

---

## 5. Schema and data quality

| Priority | Item | Notes |
|----------|------|--------|
| P2 | **dlt `columns` hints** | Reduce “column not materialized” warnings for sparse fields. |
| P2 | **Endpoint config** | Typed config per endpoint: `path`, `limit`, `required_scope`, `enabled`. Skip or mark 403 as “skipped — scope” vs hard failure. |

---

## 6. Security and compliance

- Never commit `.env`, client secrets, or refresh tokens.
- **Production** (e.g. SPCS): OAuth app + minimal scopes + `BEXIO_REFRESH_TOKEN_FILE` on persistent storage where rotation is required.
- Document who owns the bexio app registration and redirect URIs.

---

## Suggested implementation order

1. Finish OAuth in Snowflake secrets + confirm one successful SPCS run with refresh token only.
2. Switch dlt destination to Snowflake; validate one table end-to-end.
3. Change write disposition to **append** (or merge) and define PSA retention / dedupe rules.
4. Add 429-aware retry and optional incremental endpoints.

This file can live in-repo as the single roadmap for connector hardening until tickets replace it.
