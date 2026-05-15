#!/usr/bin/env bash
# Execute the Bexio dlt SPCS job (container starts, runs pipeline, exits).
#
# Usage:
#   ./spcs/execute_job.sh --env dev           # sync: wait until finished
#   ./spcs/execute_job.sh --env dev --async   # return after job is submitted

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME="dev"
CONNECTION_OVERRIDE=""
ASYNC_FLAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --connection|-c) CONNECTION_OVERRIDE="$2"; shift 2 ;;
    --async) ASYNC_FLAG="ASYNC"; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

set -a && source "${SCRIPT_DIR}/config/${ENV_NAME}.env" && set +a
CONNECTION="${CONNECTION_OVERRIDE:-${SNOW_CONNECTION:-bexio-dlt}}"

SERVICE_FQN="${DB_NAME}.${SCHEMA}.${JOB_SERVICE}"
echo "→ EXECUTE JOB SERVICE ${SERVICE_FQN} ${ASYNC_FLAG}"

if [[ -n "$ASYNC_FLAG" ]]; then
  snow sql -c "$CONNECTION" -q "EXECUTE JOB SERVICE ${SERVICE_FQN} ASYNC;"
  echo "✓ Job submitted. Monitor: snow spcs service list-jobs -c ${CONNECTION}"
else
  snow sql -c "$CONNECTION" -q "EXECUTE JOB SERVICE ${SERVICE_FQN};"
  echo "✓ Job finished."
fi
