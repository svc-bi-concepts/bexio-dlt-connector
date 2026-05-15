#!/usr/bin/env bash
# One-time Snowflake bootstrap: schemas, roles, service user in RAW.
#
# Usage (as ACCOUNTADMIN connection):
#   ./spcs/bootstrap_account.sh --env dev
#   ./spcs/bootstrap_account.sh --env dev --snowpipe   # no warehouse for data loads (Snowpipe path)
#
# Then (dlt): set SVC_BEXIO_DLT password and add DLT_SNOWFLAKE_PASSWORD to .env
#      (snowpipe): no loader password — use key-pair user SNOWPIPE_REST + create_secrets.sh --snowpipe

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME="dev"
CONNECTION_OVERRIDE=""
SNOWPIPE_MODE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --connection|-c) CONNECTION_OVERRIDE="$2"; shift 2 ;;
    --snowpipe) SNOWPIPE_MODE=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

set -a && source "${SCRIPT_DIR}/config/${ENV_NAME}.env" && set +a
export DATA_SCHEMA DEPLOYER_ROLE LOADER_ROLE OPERATOR_ROLE SVC_USER
CONNECTION="${CONNECTION_OVERRIDE:-${SNOW_CONNECTION:-bexio-dlt}}"

if [[ "$SNOWPIPE_MODE" == true ]]; then
  echo "=== Bootstrap Snowpipe-only (${DB_NAME}) ==="
  envsubst < "${SCRIPT_DIR}/sql/bootstrap_raw_account_snowpipe.sql" | snow sql -c "$CONNECTION"
  echo ""
  echo "Next steps (Snowpipe):"
  echo "  1. Create key-pair user ${SNOWPIPE_REST_USER} + ${SNOWPIPE_REST_ROLE} (see spcs/SNOWPIPE.md)"
  echo "  2. GRANT ROLE ${DEPLOYER_ROLE} TO USER <you>;"
  echo "  3. Set SNOWFLAKE_EGRESS_HOSTPORT in spcs/config/${ENV_NAME}.env"
  echo "  4. ./spcs/create_secrets.sh --env ${ENV_NAME} --snowpipe"
else
  echo "=== Bootstrap ${DB_NAME}.${DATA_SCHEMA} + ${DB_NAME}.${SCHEMA} (dlt + warehouse) ==="
  envsubst < "${SCRIPT_DIR}/sql/bootstrap_raw_account.sql" | snow sql -c "$CONNECTION"
  echo ""
  echo "Next steps (dlt):"
  echo "  1. Set password: ALTER USER ${SVC_USER} SET PASSWORD = '...';"
  echo "  2. Add to .env: DLT_SNOWFLAKE_USER=${SVC_USER}  DLT_SNOWFLAKE_PASSWORD=..."
  echo "  3. GRANT ROLE ${DEPLOYER_ROLE} TO USER <you>;"
  echo "  4. ./spcs/create_secrets.sh --env ${ENV_NAME}"
fi
