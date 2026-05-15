-- Bootstrap: schemas, roles, service account for bexio-dlt-connector in existing RAW database.
-- Run once as ACCOUNTADMIN (or equivalent).
--
-- Suggested layout:
--   RAW.BEXIO       — dlt landing tables (contacts, bills, journal, …)
--   RAW.BEXIO_SPCS  — secrets, network rules, image repository (platform only)
--
-- Roles:
--   BEXIO_DLT_DEPLOYER — humans/CI: create SPCS infra, secrets, job service, task
--   BEXIO_DLT_LOADER   — service account: write landing data via dlt
--   BEXIO_DLT_OPERATOR — optional: Snowflake TASK that submits the job (if not using deployer)
--
-- Substitute via envsubst from spcs/config/<env>.env before running, e.g.:
--   set -a && source spcs/config/prd.env && set +a
--   envsubst < spcs/sql/bootstrap_raw_account.sql | snow sql -c bexio-dlt

USE ROLE ACCOUNTADMIN;

-- ── Schemas ───────────────────────────────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS ${DB_NAME}
  COMMENT = 'Raw / landing layer';

CREATE SCHEMA IF NOT EXISTS ${DB_NAME}.${DATA_SCHEMA}
  COMMENT = 'Bexio API landing tables (dlt, SCD2)';

CREATE SCHEMA IF NOT EXISTS ${DB_NAME}.${SCHEMA}
  COMMENT = 'SPCS platform objects for bexio-dlt-connector (secrets, egress)';

-- ── Warehouse (skip if you reuse an existing WH) ─────────────────────────────
CREATE WAREHOUSE IF NOT EXISTS ${WAREHOUSE}
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Bexio dlt extract/load';

-- ── Roles ─────────────────────────────────────────────────────────────────────
CREATE ROLE IF NOT EXISTS ${DEPLOYER_ROLE}
  COMMENT = 'Deploy bexio-dlt SPCS infra (pool, EAI, secrets, job service)';

CREATE ROLE IF NOT EXISTS ${LOADER_ROLE}
  COMMENT = 'Service account: load Bexio data into ${DB_NAME}.${DATA_SCHEMA}';

CREATE ROLE IF NOT EXISTS ${OPERATOR_ROLE}
  COMMENT = 'Execute scheduled Bexio dlt SPCS job (TASK owner)';

-- ── Deployer: schema + SPCS + secrets + image repo ───────────────────────────
GRANT USAGE ON DATABASE ${DB_NAME} TO ROLE ${DEPLOYER_ROLE};
GRANT USAGE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE SECRET ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE NETWORK RULE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE IMAGE REPOSITORY ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE INTEGRATION ON ACCOUNT TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE COMPUTE POOL ON ACCOUNT TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE SERVICE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT CREATE TASK ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT USAGE ON WAREHOUSE ${WAREHOUSE} TO ROLE ${DEPLOYER_ROLE};

GRANT CREATE TASK ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${OPERATOR_ROLE};
GRANT EXECUTE TASK ON ACCOUNT TO ROLE ${OPERATOR_ROLE};

-- ── Loader: landing zone only (least privilege) ───────────────────────────────
GRANT USAGE ON DATABASE ${DB_NAME} TO ROLE ${LOADER_ROLE};
GRANT USAGE ON SCHEMA ${DB_NAME}.${DATA_SCHEMA} TO ROLE ${LOADER_ROLE};
GRANT CREATE TABLE ON SCHEMA ${DB_NAME}.${DATA_SCHEMA} TO ROLE ${LOADER_ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ${DB_NAME}.${DATA_SCHEMA} TO ROLE ${LOADER_ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON FUTURE TABLES IN SCHEMA ${DB_NAME}.${DATA_SCHEMA} TO ROLE ${LOADER_ROLE};
GRANT USAGE ON WAREHOUSE ${WAREHOUSE} TO ROLE ${LOADER_ROLE};

-- dlt may create staging/internal objects in the target schema
GRANT CREATE FILE FORMAT ON SCHEMA ${DB_NAME}.${DATA_SCHEMA} TO ROLE ${LOADER_ROLE};
GRANT CREATE STAGE ON SCHEMA ${DB_NAME}.${DATA_SCHEMA} TO ROLE ${LOADER_ROLE};
GRANT CREATE VIEW ON SCHEMA ${DB_NAME}.${DATA_SCHEMA} TO ROLE ${LOADER_ROLE};

-- ── Operator: run job on schedule (no DDL on landing tables) ─────────────────
GRANT USAGE ON DATABASE ${DB_NAME} TO ROLE ${OPERATOR_ROLE};
GRANT USAGE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${OPERATOR_ROLE};
GRANT USAGE ON WAREHOUSE ${WAREHOUSE} TO ROLE ${OPERATOR_ROLE};
-- Pool / service / EAI grants are applied after deploy_infra.sql (run grant_operator.sql)

-- ── Service account ───────────────────────────────────────────────────────────
CREATE USER IF NOT EXISTS ${SVC_USER}
  TYPE = SERVICE
  DEFAULT_ROLE = ${LOADER_ROLE}
  DEFAULT_WAREHOUSE = ${WAREHOUSE}
  DEFAULT_NAMESPACE = ${DB_NAME}.${DATA_SCHEMA}
  COMMENT = 'bexio-dlt-connector dlt loader (SPCS job destination credentials)'
  MUST_CHANGE_PASSWORD = FALSE;

GRANT ROLE ${LOADER_ROLE} TO USER ${SVC_USER};

-- Optional: grant deployer to your human admin user (set DEPLOYER_USER in .env)
-- GRANT ROLE ${DEPLOYER_ROLE} TO USER ${DEPLOYER_USER};

SHOW ROLES LIKE 'BEXIO_DLT%';
SHOW GRANTS TO ROLE ${LOADER_ROLE};
SHOW GRANTS TO USER ${SVC_USER};
