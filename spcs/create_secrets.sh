#!/usr/bin/env bash
# Create Snowflake secrets for the Bexio SPCS job (dlt warehouse mode or Snowpipe mode).
#
# Reads from repo-root .env (never commit):
#   BEXIO_CLIENT_ID, BEXIO_CLIENT_SECRET, BEXIO_REFRESH_TOKEN
#   DLT_SNOWFLAKE_USER, DLT_SNOWFLAKE_PASSWORD   — default mode (warehouse/dlt)
#   SNOWPIPE_PRIVATE_KEY_PATH                     — path to RSA PEM for Snowpipe REST (optional add-on or required with --snowpipe)
#
# Usage:
#   ./spcs/create_secrets.sh --env dev
#   ./spcs/create_secrets.sh --env dev --snowpipe        # OAuth + Snowpipe key only (no dlt Snowflake password secret)
#   ./spcs/create_secrets.sh --env prd --connection my-account

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME="dev"
CONNECTION_OVERRIDE=""
SNOWPIPE_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --connection|-c) CONNECTION_OVERRIDE="$2"; shift 2 ;;
    --snowpipe) SNOWPIPE_ONLY=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

set -a && source "${SCRIPT_DIR}/config/${ENV_NAME}.env" && set +a
export DEPLOYER_ROLE OPERATOR_ROLE LOADER_ROLE
CONNECTION="${CONNECTION_OVERRIDE:-${SNOW_CONNECTION:-bexio-dlt}}"

ROOT_ENV="${SCRIPT_DIR}/../.env"
if [[ ! -f "$ROOT_ENV" ]]; then
  echo "ERROR: Missing ${ROOT_ENV}. Copy from .env.example and run oauth_login.py first." >&2
  exit 1
fi

read_var() {
  grep -E "^${1}=" "$ROOT_ENV" | cut -d= -f2- || true
}

BEXIO_CLIENT_ID=$(read_var BEXIO_CLIENT_ID)
BEXIO_CLIENT_SECRET=$(read_var BEXIO_CLIENT_SECRET)
BEXIO_REFRESH_TOKEN=$(read_var BEXIO_REFRESH_TOKEN)
DLT_SNOWFLAKE_USER=$(read_var DLT_SNOWFLAKE_USER)
DLT_SNOWFLAKE_PASSWORD=$(read_var DLT_SNOWFLAKE_PASSWORD)
SNOWPIPE_PRIVATE_KEY_PATH=$(read_var SNOWPIPE_PRIVATE_KEY_PATH)

for var in BEXIO_CLIENT_ID BEXIO_CLIENT_SECRET BEXIO_REFRESH_TOKEN; do
  if [[ -z "${!var}" ]]; then
    echo "ERROR: ${var} not set in ${ROOT_ENV}" >&2
    exit 1
  fi
done

if [[ "$SNOWPIPE_ONLY" != true ]]; then
  if [[ -z "${DLT_SNOWFLAKE_PASSWORD}" ]]; then
    echo "ERROR: DLT_SNOWFLAKE_PASSWORD not set in ${ROOT_ENV} (or use --snowpipe)" >&2
    exit 1
  fi
fi

if [[ -z "${DLT_SNOWFLAKE_USER}" ]]; then
  DLT_SNOWFLAKE_USER=$(read_var SNOWFLAKE_USER)
fi
if [[ "$SNOWPIPE_ONLY" != true ]] && [[ -z "${DLT_SNOWFLAKE_USER}" ]]; then
  echo "ERROR: Set DLT_SNOWFLAKE_USER (or SNOWFLAKE_USER) in ${ROOT_ENV}" >&2
  exit 1
fi

escape_sql() {
  printf '%s' "$1" | sed "s/'/''/g"
}

resolve_pem_path() {
  local p="$1"
  [[ -n "$p" ]] || return 1
  if [[ "$p" != /* ]]; then
    p="${SCRIPT_DIR}/../${p}"
  fi
  printf '%s' "$p"
}

pem_sql_escape() {
  python3 -c "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text().replace(\"'\",\"''\"))" "$1"
}

CID=$(escape_sql "$BEXIO_CLIENT_ID")
CSEC=$(escape_sql "$BEXIO_CLIENT_SECRET")
RTOK=$(escape_sql "$BEXIO_REFRESH_TOKEN")

need_snowpipe_secret=false
if [[ "$SNOWPIPE_ONLY" == true ]]; then
  need_snowpipe_secret=true
elif [[ -n "${SNOWPIPE_PRIVATE_KEY_PATH}" ]]; then
  need_snowpipe_secret=true
fi

if [[ "$need_snowpipe_secret" == true ]]; then
  PEM_PATH="$(resolve_pem_path "${SNOWPIPE_PRIVATE_KEY_PATH}")" || true
  if [[ ! -f "${PEM_PATH:-}" ]]; then
    echo "ERROR: SNOWPIPE_PRIVATE_KEY_PATH must point to an RSA PEM file (resolved: ${PEM_PATH:-empty})" >&2
    exit 1
  fi
  PEM_ESC=$(pem_sql_escape "$PEM_PATH")
fi

echo "→ Creating secrets in ${DB_NAME}.${SCHEMA} (connection: ${CONNECTION})..."

if [[ "$SNOWPIPE_ONLY" == true ]]; then
  snow sql -c "$CONNECTION" <<SQL
USE ROLE ${DEPLOYER_ROLE:-BEXIO_DLT_DEPLOYER};
CREATE SCHEMA IF NOT EXISTS ${DB_NAME}.${SCHEMA};

CREATE OR REPLACE SECRET ${DB_NAME}.${SCHEMA}.BEXIO_CLIENT_ID
  TYPE = GENERIC_STRING
  SECRET_STRING = '${CID}';

CREATE OR REPLACE SECRET ${DB_NAME}.${SCHEMA}.BEXIO_CLIENT_SECRET
  TYPE = GENERIC_STRING
  SECRET_STRING = '${CSEC}';

CREATE OR REPLACE SECRET ${DB_NAME}.${SCHEMA}.BEXIO_REFRESH_TOKEN
  TYPE = GENERIC_STRING
  SECRET_STRING = '${RTOK}';

CREATE OR REPLACE SECRET ${DB_NAME}.${SCHEMA}.SNOWPIPE_PRIVATE_KEY_PEM
  TYPE = GENERIC_STRING
  SECRET_STRING = '${PEM_ESC}';

GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.BEXIO_CLIENT_ID TO ROLE ${OPERATOR_ROLE:-BEXIO_DLT_OPERATOR};
GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.BEXIO_CLIENT_SECRET TO ROLE ${OPERATOR_ROLE:-BEXIO_DLT_OPERATOR};
GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.BEXIO_REFRESH_TOKEN TO ROLE ${OPERATOR_ROLE:-BEXIO_DLT_OPERATOR};
GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.SNOWPIPE_PRIVATE_KEY_PEM TO ROLE ${OPERATOR_ROLE:-BEXIO_DLT_OPERATOR};
GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.SNOWPIPE_PRIVATE_KEY_PEM TO ROLE ${LOADER_ROLE:-BEXIO_DLT_LOADER};
SQL
else
  SPWD=$(escape_sql "$DLT_SNOWFLAKE_PASSWORD")
  snow sql -c "$CONNECTION" <<SQL
USE ROLE ${DEPLOYER_ROLE:-BEXIO_DLT_DEPLOYER};
CREATE SCHEMA IF NOT EXISTS ${DB_NAME}.${SCHEMA};

CREATE OR REPLACE SECRET ${DB_NAME}.${SCHEMA}.BEXIO_CLIENT_ID
  TYPE = GENERIC_STRING
  SECRET_STRING = '${CID}';

CREATE OR REPLACE SECRET ${DB_NAME}.${SCHEMA}.BEXIO_CLIENT_SECRET
  TYPE = GENERIC_STRING
  SECRET_STRING = '${CSEC}';

CREATE OR REPLACE SECRET ${DB_NAME}.${SCHEMA}.BEXIO_REFRESH_TOKEN
  TYPE = GENERIC_STRING
  SECRET_STRING = '${RTOK}';

CREATE OR REPLACE SECRET ${DB_NAME}.${SCHEMA}.DLT_SNOWFLAKE_PASSWORD
  TYPE = GENERIC_STRING
  SECRET_STRING = '${SPWD}';

GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.BEXIO_CLIENT_ID TO ROLE ${OPERATOR_ROLE:-BEXIO_DLT_OPERATOR};
GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.BEXIO_CLIENT_SECRET TO ROLE ${OPERATOR_ROLE:-BEXIO_DLT_OPERATOR};
GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.BEXIO_REFRESH_TOKEN TO ROLE ${OPERATOR_ROLE:-BEXIO_DLT_OPERATOR};
GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.DLT_SNOWFLAKE_PASSWORD TO ROLE ${OPERATOR_ROLE:-BEXIO_DLT_OPERATOR};
SQL

  if [[ "$need_snowpipe_secret" == true ]]; then
    snow sql -c "$CONNECTION" <<SQL
USE ROLE ${DEPLOYER_ROLE:-BEXIO_DLT_DEPLOYER};
CREATE OR REPLACE SECRET ${DB_NAME}.${SCHEMA}.SNOWPIPE_PRIVATE_KEY_PEM
  TYPE = GENERIC_STRING
  SECRET_STRING = '${PEM_ESC}';
GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.SNOWPIPE_PRIVATE_KEY_PEM TO ROLE ${OPERATOR_ROLE:-BEXIO_DLT_OPERATOR};
GRANT READ ON SECRET ${DB_NAME}.${SCHEMA}.SNOWPIPE_PRIVATE_KEY_PEM TO ROLE ${LOADER_ROLE:-BEXIO_DLT_LOADER};
SQL
  fi
fi

echo "✓ Secrets created."
echo "  Next: ./spcs/push_image.sh --env ${ENV_NAME}"
