-- Bootstrap (Snowpipe-only): no classic warehouse for **data loads** (Snowpipe serverless COPY).
-- SPCS still uses a **compute pool** (separate from virtual warehouses).
--
-- Scheduling: native Snowflake `CREATE TASK ... EXECUTE JOB SERVICE` still requires
-- `WAREHOUSE = ...` on the task. If you need **zero** virtual warehouses, run the job on a
-- schedule outside Snowflake TASKs (e.g. CI cron + `snow spcs`) or accept a tiny XSMALL task WH.
--
-- Run once as ACCOUNTADMIN:
--   set -a && source spcs/config/dev.env && set +a
--   envsubst < spcs/sql/bootstrap_raw_account_snowpipe.sql | snow sql -c <conn>

USE ROLE ACCOUNTADMIN;

CREATE DATABASE IF NOT EXISTS ${DB_NAME}
  COMMENT = 'Raw / landing layer';

CREATE SCHEMA IF NOT EXISTS ${DB_NAME}.${DATA_SCHEMA}
  COMMENT = 'Bexio landing (Snowpipe VARIANT + optional downstream models)';

CREATE SCHEMA IF NOT EXISTS ${DB_NAME}.${SCHEMA}
  COMMENT = 'SPCS: secrets, egress, image repo, Snowpipe stage/pipe, job service';

-- ── Roles ─────────────────────────────────────────────────────────────────────
CREATE ROLE IF NOT EXISTS ${DEPLOYER_ROLE}
  COMMENT = 'Deploy bexio SPCS (Snowpipe path)';

CREATE ROLE IF NOT EXISTS ${LOADER_ROLE}
  COMMENT = 'SPCS job runtime role (minimal; no warehouse for loads)';

CREATE ROLE IF NOT EXISTS ${OPERATOR_ROLE}
  COMMENT = 'Execute / schedule Bexio SPCS job';

-- ── Deployer ──────────────────────────────────────────────────────────────────
GRANT USAGE ON DATABASE ${DB_NAME} TO ROLE ${DEPLOYER_ROLE};
GRANT USAGE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT USAGE ON SCHEMA ${DB_NAME}.${DATA_SCHEMA} TO ROLE ${DEPLOYER_ROLE};

GRANT CREATE SECRET ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE NETWORK RULE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE IMAGE REPOSITORY ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE INTEGRATION ON ACCOUNT TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE COMPUTE POOL ON ACCOUNT TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE SERVICE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE TASK ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE STAGE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE PIPE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE TABLE ON SCHEMA ${DB_NAME}.${DATA_SCHEMA} TO ROLE ${DEPLOYER_ROLE};

-- ── Loader (SPCS service user default role) ───────────────────────────────────
GRANT USAGE ON DATABASE ${DB_NAME} TO ROLE ${LOADER_ROLE};
GRANT USAGE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${LOADER_ROLE};

-- ── Operator ──────────────────────────────────────────────────────────────────
GRANT USAGE ON DATABASE ${DB_NAME} TO ROLE ${OPERATOR_ROLE};
GRANT USAGE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${OPERATOR_ROLE};

GRANT CREATE TASK ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${OPERATOR_ROLE};
GRANT EXECUTE TASK ON ACCOUNT TO ROLE ${OPERATOR_ROLE};

-- ── Service account (no DEFAULT_WAREHOUSE — Snowpipe + pool only) ─────────────
CREATE USER IF NOT EXISTS ${SVC_USER}
  TYPE = SERVICE
  DEFAULT_ROLE = ${LOADER_ROLE}
  COMMENT = 'bexio-connector SPCS job (Snowpipe mode)'
  MUST_CHANGE_PASSWORD = FALSE;

GRANT ROLE ${LOADER_ROLE} TO USER ${SVC_USER};

SHOW ROLES LIKE 'BEXIO_DLT%';
SHOW GRANTS TO ROLE ${LOADER_ROLE};
