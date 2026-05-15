#!/usr/bin/env bash
# Create or replace the SPCS *job service* (batch — not a long-running service).
#
# Usage:
#   ./spcs/deploy_job.sh --env dev
# Snowpipe (stage volume + insertFiles): set JOB_SPEC_TMPL to job_snowpipe.yaml.tmpl
#   JOB_SPEC_TMPL="$(pwd)/spcs/job_snowpipe.yaml.tmpl" ./spcs/deploy_job.sh --env dev

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME="dev"
CONNECTION_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --connection|-c) CONNECTION_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

set -a && source "${SCRIPT_DIR}/config/${ENV_NAME}.env" && set +a
CONNECTION="${CONNECTION_OVERRIDE:-${SNOW_CONNECTION:-bexio-dlt}}"

# Load Snowflake account for dlt host if set in root .env
ROOT_ENV="${SCRIPT_DIR}/../.env"
if [[ -f "$ROOT_ENV" ]]; then
  SNOWFLAKE_ACCOUNT=$(grep -E '^SNOWFLAKE_ACCOUNT=' "$ROOT_ENV" | cut -d= -f2- || true)
  SNOWFLAKE_HOST=$(grep -E '^SNOWFLAKE_HOST=' "$ROOT_ENV" | cut -d= -f2- || true)
  DLT_SNOWFLAKE_USER=$(grep -E '^DLT_SNOWFLAKE_USER=' "$ROOT_ENV" | cut -d= -f2- || true)
  if [[ -z "${DLT_SNOWFLAKE_USER}" ]]; then
    DLT_SNOWFLAKE_USER=$(grep -E '^SNOWFLAKE_USER=' "$ROOT_ENV" | cut -d= -f2- || true)
  fi
fi
if [[ -z "${SNOWFLAKE_HOST:-}" && -n "${SNOWFLAKE_ACCOUNT:-}" ]]; then
  SNOWFLAKE_HOST="${SNOWFLAKE_ACCOUNT}.snowflakecomputing.com"
fi

JOB_SPEC_TMPL="${JOB_SPEC_TMPL:-${SCRIPT_DIR}/job.yaml.tmpl}"
if [[ ! -f "${JOB_SPEC_TMPL}" ]]; then
  echo "ERROR: JOB_SPEC_TMPL not found: ${JOB_SPEC_TMPL}" >&2
  exit 1
fi

if [[ "$(basename "${JOB_SPEC_TMPL}")" == "job_snowpipe.yaml.tmpl" ]]; then
  if [[ -z "${SNOWFLAKE_HOST:-}" || -z "${SNOWFLAKE_ACCOUNT:-}" ]]; then
    echo "ERROR: Snowpipe job needs SNOWFLAKE_ACCOUNT and SNOWFLAKE_HOST (or derivable host) in ${ROOT_ENV}" >&2
    exit 1
  fi
  if [[ -z "${SNOWPIPE_REST_USER:-}" ]]; then
    echo "ERROR: Set SNOWPIPE_REST_USER in spcs/config/${ENV_NAME}.env (key-pair user for insertFiles)." >&2
    exit 1
  fi
  export SNOWPIPE_REST_USER SNOWPIPE_REST_ROLE LOADER_ROLE SNOWFLAKE_HOST SNOWFLAKE_ACCOUNT
else
  if [[ -z "${SNOWFLAKE_HOST:-}" || -z "${DLT_SNOWFLAKE_USER:-}" ]]; then
    echo "ERROR: Set SNOWFLAKE_ACCOUNT (or SNOWFLAKE_HOST) and DLT_SNOWFLAKE_USER in ${ROOT_ENV}" >&2
    exit 1
  fi
  export SNOWFLAKE_HOST DLT_SNOWFLAKE_USER LOADER_ROLE
fi

SPEC_OUT="/tmp/bexio-dlt-job-${ENV_NAME}.yaml"
envsubst < "${JOB_SPEC_TMPL}" > "${SPEC_OUT}"

SERVICE_FQN="${DB_NAME}.${SCHEMA}.${JOB_SERVICE}"
echo "→ Creating SPCS job service ${SERVICE_FQN}"
echo "  spec: ${SPEC_OUT}"

# Drop if exists (job service recreate pattern)
snow sql -c "$CONNECTION" -q "DROP SERVICE IF EXISTS ${SERVICE_FQN};" || true

snow spcs service create "${JOB_SERVICE}" \
  --compute-pool "${COMPUTE_POOL}" \
  --spec-path "${SPEC_OUT}" \
  --eai-name "${BEXIO_EAI}" \
  --database "${DB_NAME}" \
  --schema "${SCHEMA}" \
  -c "$CONNECTION"

echo "✓ Job service ${SERVICE_FQN} created."
echo "  Run once: ./spcs/execute_job.sh --env ${ENV_NAME}"
