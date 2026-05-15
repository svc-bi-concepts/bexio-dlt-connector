#!/usr/bin/env bash
# Create compute pool, image repo, network rule, EAI, optional schedule task.
#
# Usage:
#   ./spcs/deploy_infra.sh --env dev
#   ./spcs/deploy_infra.sh --env prd --with-task
#
# Snowpipe-only path (no DLT / no loader warehouse password secret):
#   Set SNOWFLAKE_EGRESS_HOSTPORT in spcs/config/<env>.env (e.g. xy12345.eu-central-1.aws.snowflakecomputing.com:443)
#   ./spcs/deploy_infra.sh --env dev --snowpipe
#
# Note: --with-task + --snowpipe skips the Snowflake TASK (TASK syntax requires a virtual warehouse).
#       Use CI/cron + ./spcs/execute_job.sh, or accept a tiny WH for scheduling only.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME="dev"
CONNECTION_OVERRIDE=""
WITH_TASK=false
SNOWPIPE_MODE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --connection|-c) CONNECTION_OVERRIDE="$2"; shift 2 ;;
    --with-task) WITH_TASK=true; shift ;;
    --snowpipe) SNOWPIPE_MODE=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

set -a && source "${SCRIPT_DIR}/config/${ENV_NAME}.env" && set +a
export DEPLOYER_ROLE LOADER_ROLE OPERATOR_ROLE DATA_SCHEMA
CONNECTION="${CONNECTION_OVERRIDE:-${SNOW_CONNECTION:-bexio-dlt}}"

run_sql() {
  local file="$1"
  echo "→ ${file}"
  envsubst < "${SCRIPT_DIR}/sql/${file}" | snow sql -c "$CONNECTION"
}

echo "=== Bexio SPCS infra (${ENV_UPPER})${SNOWPIPE_MODE:+ [snowpipe]} ==="
run_sql compute_pool.sql

if [[ "$SNOWPIPE_MODE" == true ]]; then
  if [[ -z "${SNOWFLAKE_EGRESS_HOSTPORT:-}" ]]; then
    echo "ERROR: Set SNOWFLAKE_EGRESS_HOSTPORT in spcs/config/${ENV_NAME}.env" >&2
    echo "  Example: xy12345.eu-central-1.aws.snowflakecomputing.com:443 (no https://)" >&2
    exit 1
  fi
  export SNOWFLAKE_EGRESS_HOSTPORT
  run_sql network_rule_snowpipe.sql
else
  run_sql network_rule.sql
fi

echo "→ Ensure secrets exist (spcs/create_secrets.sh) before EAI"
if [[ "$SNOWPIPE_MODE" == true ]]; then
  run_sql external_access_integration_snowpipe.sql
else
  run_sql external_access_integration.sql
fi

if [[ "$WITH_TASK" == true ]]; then
  if [[ "$SNOWPIPE_MODE" == true ]]; then
    echo "⚠ Skipping schedule_task: Snowflake TASK requires WAREHOUSE= on the task object."
    echo "  Run jobs via ./spcs/execute_job.sh (manual/CI) or add a dedicated schedule path with a minimal warehouse."
  else
    echo "→ schedule_task.sql.tmpl"
    envsubst < "${SCRIPT_DIR}/sql/schedule_task.sql.tmpl" | snow sql -c "$CONNECTION"
  fi
fi

echo "→ grant_operator post-deploy (if job service already exists)"
if snow sql -c "$CONNECTION" -q "DESCRIBE SERVICE ${DB_NAME}.${SCHEMA}.${JOB_SERVICE};" &>/dev/null; then
  if [[ "$SNOWPIPE_MODE" == true ]]; then
    envsubst < "${SCRIPT_DIR}/sql/grant_operator_post_deploy_snowpipe.sql" | snow sql -c "$CONNECTION"
  else
    envsubst < "${SCRIPT_DIR}/sql/grant_operator_post_deploy.sql" | snow sql -c "$CONNECTION"
  fi
else
  echo "  (skip — create job service first, then re-run deploy_infra or apply grant_operator_post_deploy*.sql)"
fi

echo "✓ Infra ready. Deploy job:"
echo "    export JOB_SPEC_TMPL=\"\$(pwd)/spcs/job_snowpipe.yaml.tmpl\"   # if --snowpipe"
echo "    ./spcs/deploy_job.sh --env ${ENV_NAME}"
