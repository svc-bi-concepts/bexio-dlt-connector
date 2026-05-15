# Snowpark Container Services (SPCS) — Bexio → Snowflake

**Snowpipe-only (no virtual warehouse for data load):** use **[`SNOWPIPE.md`](SNOWPIPE.md)** — `$ ./spcs/bootstrap_account.sh --snowpipe`, `create_secrets.sh --snowpipe`, `deploy_infra.sh --snowpipe`, `JOB_SPEC_TMPL=.../job_snowpipe.yaml.tmpl ./spcs/deploy_job.sh`.

**dlt + warehouse (SCD2 merge):** this README below.

---

Run `dlt_pipeline.py` as a **batch SPCS job**: the container **starts, extracts all configured Bexio endpoints, loads Snowflake, and exits**. No always-on service, no public endpoints.

Warehouse-side **incremental** behaviour is already handled by dlt **SCD2 merge** (`row_hash`); each run still **full-scans** the Bexio API (see [IMPROVEMENT_PLAN.md](../IMPROVEMENT_PLAN.md) for API-level incremental later).

---

## Efficiency: smallest container, shortest runtime

These choices keep cost low — you pay for compute **only while the pipeline runs**, not 24/7.

| Choice | Why it saves money |
|--------|-------------------|
| **Job service, not a service** | `EXECUTE JOB SERVICE` runs the container once and **stops when `dlt_pipeline.py` exits**. Unlike doc_proc’s HTTP service, nothing idles between schedules. |
| **Compute pool `MIN_NODES = 0`** | Pool **scales to zero** when no job is running ([`sql/compute_pool.sql`](sql/compute_pool.sql)). |
| **`AUTO_SUSPEND_SECS = 60`** | Suspends idle pool nodes quickly after a job finishes. |
| **`INSTANCE_FAMILY = CPU_X64_XS`** | Smallest SPCS instance size. |
| **Container `0.25` CPU, `512Mi` RAM** | Minimal requests in [`job.yaml.tmpl`](job.yaml.tmpl). If the run OOMs on large tables (e.g. `journal`), raise memory to `1Gi` only. |
| **No ingress / endpoints** | Job spec has no `endpoints:` block — no load balancer, no public URL. |
| **Single replica** | Default one job instance; do not set `REPLICAS` unless you shard endpoints manually. |
| **Daily TASK with `ASYNC`** | [`schedule_task.sql.tmpl`](sql/schedule_task.sql.tmpl) submits the job and returns; the warehouse task does not hold a slot for the full extract duration. |
| **1Gi block volume** | Persists `.dlt` state + rotated OAuth refresh token only — not full PDF/file storage. |
| **Skip inbox `files` in prod** | Optional: remove `files` from `ENDPOINTS` in `dlt_pipeline.py` if you only need structured entities (saves API time). |

**Typical timeline:** pool resumes → container starts → OAuth refresh → ~34 endpoint paginated GETs → dlt merge to Snowflake → container exits → pool suspends.

Monitor duration with `snow spcs service list-jobs` and tune memory if needed.

---

## Snowflake layout (existing `RAW` database)

Recommended naming (already reflected in `spcs/config/*.env`):

| Object | Name | Purpose |
|--------|------|---------|
| Database | **`RAW`** | Your existing raw / landing DB |
| Schema | **`RAW.BEXIO`** | dlt tables (`contacts`, `bills`, `journal`, …) |
| Schema | **`RAW.BEXIO_SPCS`** | Secrets, network rule, image repo, job service, TASK |
| Service user | **`SVC_BEXIO_DLT`** | dlt connects as this user (`BEXIO_DLT_LOADER` role) |
| Role | **`BEXIO_DLT_LOADER`** | Write access to `RAW.BEXIO` only |
| Role | **`BEXIO_DLT_DEPLOYER`** | Create SPCS infra + secrets (humans / CI) |
| Role | **`BEXIO_DLT_OPERATOR`** | Run `EXECUTE JOB SERVICE` + own the daily TASK |
| Warehouse | **`BEXIO_DLT_WH`** | Small WH for extract (or reuse an existing WH) |

**Why two schemas?** Keeps platform objects separate from landing tables so the loader role cannot read OAuth secrets and deployer/operator duties stay clear.

### One-time account bootstrap

```bash
# 1. As ACCOUNTADMIN (snow connection)
./spcs/bootstrap_account.sh --env dev

# 2. Set service account password
snow sql -c bexio-dlt -q "ALTER USER SVC_BEXIO_DLT SET PASSWORD = '...';"

# 3. Grant deployer role to your user
snow sql -c bexio-dlt -q "GRANT ROLE BEXIO_DLT_DEPLOYER TO USER your.name@company.ch;"

# 4. Add to .env (see .env.spcs.example)
#    DLT_SNOWFLAKE_USER=SVC_BEXIO_DLT
#    DLT_SNOWFLAKE_PASSWORD=...
```

Then continue with secrets → image → infra → job (below).

---

## Prerequisites

- Snowflake account with **Snowpark Container Services** enabled
- [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli) (`snow`) configured (`snow connection add`)
- Docker (build `linux/amd64` image)
- Bexio OAuth app + refresh token ([AUTHENTICATION.md](../AUTHENTICATION.md))
- Repo-root `.env` with credentials (see [.env.spcs.example](../.env.spcs.example))

---

## Layout

```text
spcs/
  config/dev.env|uat.env|prd.env   # DB name, pool, warehouse, connection name
  sql/                             # Compute pool, network rule, EAI, TASK, Snowpipe DDL
  job.yaml.tmpl                    # SPCS job spec — dlt + warehouse (envsubst)
  job_snowpipe.yaml.tmpl           # Optional Snowpipe job (stage volume + JWT insertFiles)
  entrypoint.sh                    # Persist state, run pipeline, exit
  create_secrets.sh
  push_image.sh
  deploy_infra.sh
  deploy_job.sh
  execute_job.sh
```

---

## One-time setup (per environment)

Edit `spcs/config/<env>.env` (database, warehouse, pool names).

### 1. Bootstrap OAuth locally

```bash
python oauth_login.py   # copy BEXIO_REFRESH_TOKEN into .env
```

### 2. Snowflake secrets

Add to `.env`: `DLT_SNOWFLAKE_USER`, `DLT_SNOWFLAKE_PASSWORD`, `SNOWFLAKE_ACCOUNT`.

```bash
chmod +x spcs/*.sh
./spcs/create_secrets.sh --env dev
```

### 3. Infra (compute pool, **image repository**, network rule, EAI)

Run this **before** `push_image.sh` — [`sql/compute_pool.sql`](sql/compute_pool.sql) creates the Snowflake image repo your Docker push targets.

```bash
./spcs/deploy_infra.sh --env dev
```

Create the target database/warehouse/role grants in your org if `SYSADMIN` is not sufficient for dlt loads.

### 4. Build and push image

```bash
./spcs/push_image.sh --env dev
```

### 5. Register job service

```bash
./spcs/deploy_job.sh --env dev
```

### 6. Test run (sync — waits until pipeline completes)

```bash
./spcs/execute_job.sh --env dev
```

### 7. Schedule daily (optional)

```bash
./spcs/deploy_infra.sh --env dev --with-task
```

Or run async manually:

```bash
./spcs/execute_job.sh --env dev --async
```

---

## Runtime environment (job container)

| Variable | Source |
|----------|--------|
| `BEXIO_CLIENT_ID` / `SECRET` / `REFRESH_TOKEN` | Snowflake secrets |
| `BEXIO_REFRESH_TOKEN_FILE` | `/data/bexio_refresh_token` (block volume; survives rotation) |
| `BEXIO_DATA_DIR` | `/data` — see `loader_state/` below |
| Loader observability | `${BEXIO_DATA_DIR}/loader_state/last_run.json`, `history/*.json` (full per-run archive), `fingerprints/*.json` ([`loader_state.py`](../loader_state.py)) |
| `BEXIO_DLT_DESTINATION` | `snowflake` |
| `DESTINATION__SNOWFLAKE__*` | job spec + `DLT_SNOWFLAKE_PASSWORD` secret |
| `PIPELINE_RUN_ID` | `SNOWFLAKE_JOB_ID` or timestamp ([`entrypoint.sh`](entrypoint.sh)) |

Persistent paths on the block volume:

- `/data/.dlt/` — dlt pipeline state (required for stable incremental loads)
- `/data/loader_state/` — `last_run.json` (latest run only), `history/*.json` (one immutable snapshot per completed pipeline run), `fingerprints/<table>.json`
- `/data/bexio_refresh_token` — OAuth refresh rotation

---

## Operations

```bash
# Job status / history
snow spcs service list-jobs BEXIO_DLT_JOB --database DEV_BEXIO_DLT --schema CORE -c bexio-dlt

# Logs
snow spcs service logs BEXIO_DLT_JOB --database DEV_BEXIO_DLT --schema CORE -c bexio-dlt

# Re-deploy after code change
./spcs/push_image.sh --env dev
./spcs/deploy_job.sh --env dev
```

Check pipeline logs for the per-endpoint summary (`ok`, `skipped_forbidden`, `failed`).

---

## Security notes

- Network rule allows **`api.bexio.com`** and **`auth.bexio.com`** only.
- Use a **dedicated** Snowflake loader user with minimal grants on `${DB_NAME}.${BEXIO_DLT_DATASET_NAME}`.
- Never bake secrets into the Docker image.
- Prefer **refresh token file on volume** over static `BEXIO_REFRESH_TOKEN` secret after first run (secret seeds the file once via [`entrypoint.sh`](entrypoint.sh)).

---

## Related docs

- [AUTHENTICATION.md](../AUTHENTICATION.md) — OAuth bootstrap
- [IMPROVEMENT_PLAN.md](../IMPROVEMENT_PLAN.md) — SCD2, API incremental, 429 handling
- [SNOWPIPE.md](SNOWPIPE.md) — optional **Snowpipe** path (stage NDJSON → pipe → `VARIANT` landing; no warehouse for the pipe `COPY`)
- [dlt Snowflake destination](https://dlthub.com/docs/dlt-ecosystem/destinations/snowflake)
