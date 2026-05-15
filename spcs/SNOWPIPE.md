# Snowpipe mode (no warehouse for COPY ingest)

Run Bexio extract in **SPCS**, write **newline-delimited JSON** (NDJSON) to an **internal stage** mounted into the container, then call **Snowpipe REST `insertFiles`** so Snowflake loads rows using **Snowflake-managed Snowpipe compute** (see [Snowpipe](https://docs.snowflake.com/en/user-guide/data-load-snowpipe) — billed **per GB**, not classic warehouse minutes for that ingest).

This replaces **dlt → Snowflake warehouse MERGE** with:

```text
Container → stage volume (@RAW.BEXIO_SPCS.BEXIO_INGEST_STAGE)
        → Snowpipe pipe COPY INTO RAW.BEXIO.BEXIO_PIPE_LANDING (VARIANT payload + metadata)
```

---

## Deploy Snowpipe-only (no virtual warehouse for data load)

Compute pool and SPCS still bill separately; ingest uses **Snowpipe**, not your WH.

1. **Tooling:** Snowflake with **SPCS**, **Snow CLI** (`snow`), **Docker** (`linux/amd64`), repo `.env` with Bexio OAuth (`AUTHENTICATION.md`).
2. **`spcs/config/<env>.env`:** set **`SNOWFLAKE_EGRESS_HOSTPORT`** to your account REST endpoint, e.g. `xy12345.eu-central-1.aws.snowflakecomputing.com:443` (same host as `SNOWFLAKE_HOST` in root `.env`, without `https://`). Required for **`deploy_infra.sh --snowpipe`** (network rule + EAI).
3. **Bootstrap** (as `ACCOUNTADMIN`):
   ```bash
   ./spcs/bootstrap_account.sh --env dev --snowpipe
   ```
4. **Grant deployer to your user:** `GRANT ROLE BEXIO_DLT_DEPLOYER TO USER you@…;`
5. **Snowpipe REST identity:** create **`BEXIO_SNOWPIPE_REST`** + user **`SNOWPIPE_REST`** (or names in config) with **RSA key pair**; run:
   ```bash
   set -a && source spcs/config/dev.env && set +a
   export DEPLOYER_ROLE DATA_SCHEMA SNOWPIPE_REST_ROLE SNOWPIPE_REST_USER
   envsubst < spcs/sql/snowpipe_stage_pipe.sql | snow sql -c …
   envsubst < spcs/sql/snowpipe_grants.sql | snow sql -c …
   ```
6. **Secrets** (OAuth + PEM file path in `.env`):
   ```bash
   ./spcs/create_secrets.sh --env dev --snowpipe
   ```
7. **Infra** (pool, image repo, **Snowpipe-aware** network rule + EAI):
   ```bash
   ./spcs/deploy_infra.sh --env dev --snowpipe
   ```
8. **Image:** `./spcs/push_image.sh --env dev`
9. **Job service** (Snowpipe spec):
   ```bash
   export JOB_SPEC_TMPL="$(pwd)/spcs/job_snowpipe.yaml.tmpl"
   ./spcs/deploy_job.sh --env dev
   ```
   Root `.env` needs **`SNOWFLAKE_ACCOUNT`**, **`SNOWFLAKE_HOST`** for deploy rendering.
10. **Operator grants** if not applied automatically: `envsubst < spcs/sql/grant_operator_post_deploy_snowpipe.sql | snow sql -c …` (as `ACCOUNTADMIN`).
11. **Run:** `./spcs/execute_job.sh --env dev`

**Scheduling:** `deploy_infra.sh --with-task` is **skipped** when combined with **`--snowpipe`**, because Snowflake **TASK** objects still require **`WAREHOUSE =`**. Use **CI/cron** calling `execute_job.sh`, or introduce a **minimal warehouse only for the TASK** in a follow-up template.

---

## What you gain vs dlt + warehouse

| | **dlt + WH** | **Snowpipe mode** |
|--|----------------|-------------------|
| COPY / pipe ingest | Uses your warehouse | **[Snowflake-supplied Snowpipe compute](https://docs.snowflake.com/en/user-guide/data-load-snowpipe-intro)** |
| Programmatic trigger | N/A | **[Snowpipe REST insertFiles](https://docs.snowflake.com/en/user-guide/data-load-snowpipe-rest-overview)** + **[JWT key pair](https://docs.snowflake.com/en/developer-guide/sql-api/authenticating#label-sql-api-authenticating-key-pair)** |
| Relational “tables” | dlt flattened + SCD2 | **`PAYLOAD` VARIANT** per row + optional downstream modeling |

---

## Important limits (read before committing)

1. **No automatic SCD2**: This mode loads **append-style** rows into `BEXIO_PIPE_LANDING`. You lose **dlt merge/scd2** unless you add a **second step** (Dynamic Tables, tasks with MERGE, dbt, etc.) — those typically **use a warehouse** again.

2. **Transform “to columns”**: The pipe uses **[COPY with SELECT](https://docs.snowflake.com/en/sql-reference/sql/create-pipe)** to peel `_extract_run_id`, `_loaded_at`, `_resource`, and **`payload` VARIANT**. Fully flattening hundreds of dynamic keys **inside** the pipe is brittle; prefer **VARIANT + views** or a downstream modeling layer.

3. **Snowflake TASK still lists a warehouse**: If you schedule with `CREATE TASK ... WAREHOUSE = ... EXECUTE JOB SERVICE`, Snowflake **still requires a warehouse on the TASK definition** — often **seconds/day** on `XSMALL`. There is **no Snowflake-native way** to schedule purely serverless arbitrary SQL without some warehouse assignment on the task object ([TASK syntax](https://docs.snowflake.com/en/sql-reference/sql/create-task)).

4. **Egress**: The container calls **`https://<account>.snowflakecomputing.com/v1/data/pipes/...`**. Extend your **network rule / external access integration** so SPCS can reach your Snowflake REST hostname (often same host as `SNOWFLAKE_HOST`). Add the hostname to **ALLOWED_NETWORK_RULES** (see Snowflake docs on [external access](https://docs.snowflake.com/en/sql-reference/sql/create-external-access-integration)).

5. **Private key**: Snowpipe REST requires **RSA key pair JWT**, not password sessions ([REST overview](https://docs.snowflake.com/en/user-guide/data-load-snowpipe-rest-overview)).

---

## Snowflake DDL (reference)

Stage, landing table, and pipe: **`spcs/sql/snowpipe_stage_pipe.sql`** (as **`${DEPLOYER_ROLE}`**).

REST-caller grants: **`spcs/sql/snowpipe_grants.sql`** after you create the key-pair user, e.g.:

```sql
CREATE ROLE IF NOT EXISTS BEXIO_SNOWPIPE_REST;
CREATE USER IF NOT EXISTS SNOWPIPE_REST TYPE = SERVICE DEFAULT_ROLE = BEXIO_SNOWPIPE_REST;
ALTER USER SNOWPIPE_REST SET RSA_PUBLIC_KEY='MIIBIj...';
```

(`SNOWPIPE_REST_*` names come from `spcs/config/*.env`.)

If **`CREATE USER`** fails without `DEFAULT_WAREHOUSE=`, your account may require it for service users even when loads are Snowpipe-only — use a suspended **XSMALL** warehouse **only for that metadata default**, or follow current Snowflake docs for `TYPE = SERVICE` users.

---

## Container image / job spec

Use **`job_snowpipe.yaml.tmpl`** instead of `job.yaml.tmpl`:

```bash
export JOB_SPEC_TMPL="$(pwd)/spcs/job_snowpipe.yaml.tmpl"
./spcs/deploy_job.sh --env dev
```

Render manually:

```bash
envsubst < spcs/job_snowpipe.yaml.tmpl > /tmp/bexio-sp.yml
```

### Secrets / env inside the container

| Variable | Meaning |
|----------|---------|
| `BEXIO_LOAD_MODE=snowpipe` | Switches entrypoint to `snowpipe_pipeline.py` |
| `BEXIO_STAGE_MOUNT=/snowflake-stage` | Stage volume mount path |
| `SNOWPIPE_PIPE_FQN` | e.g. `RAW.BEXIO_SPCS.BEXIO_JSON_PIPE` |
| `SNOWFLAKE_ACCOUNT` | Account identifier for JWT + REST URL fallback |
| `SNOWPIPE_USER` | User login name with OPERATE on pipe + READ stage |
| `SNOWPIPE_PRIVATE_KEY_PEM` | PEM text (`\n` escaped) via Snowflake secret |
| `SNOWPIPE_PRIVATE_KEY_PASSPHRASE` | Optional passphrase |
| `SNOWFLAKE_HOST` | **Recommended** full REST hostname e.g. `xy12345.eu-central-1.aws.snowflakecomputing.com` |

---

## Code entrypoints

| File | Role |
|------|------|
| [`snowpipe_pipeline.py`](../snowpipe_pipeline.py) | Extract all endpoints → NDJSON on stage → `insertFiles` |
| [`snowflake_jwt.py`](../snowflake_jwt.py) | JWT per Snowflake SQL API key-pair recipe |
| [`snowpipe_rest.py`](../snowpipe_rest.py) | HTTP POST `insertFiles` |

---

## References

- [Snowpipe overview](https://docs.snowflake.com/en/user-guide/data-load-snowpipe)
- [Snowpipe vs bulk COPY](https://docs.snowflake.com/en/user-guide/data-load-snowpipe-intro)
- [`CREATE PIPE`](https://docs.snowflake.com/en/sql-reference/sql/create-pipe)
- [Snowpipe REST API](https://docs.snowflake.com/en/user-guide/data-load-snowpipe-rest-apis)
- [Snowflake SQL API — key pair JWT](https://docs.snowflake.com/en/developer-guide/sql-api/authenticating#label-sql-api-authenticating-key-pair)
- [Snowpipe billing](https://docs.snowflake.com/en/user-guide/data-load-snowpipe-billing)
- [Snowflake stage volume (SPCS)](https://docs.snowflake.com/en/developer-guide/snowpark-container-services/snowflake-stage-volume)
