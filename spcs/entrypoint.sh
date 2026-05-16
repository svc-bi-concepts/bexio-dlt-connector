#!/bin/sh
# SPCS job entrypoint: Snowflake session token for dlt, Bexio refresh token file, then pipeline.
set -e

# dlt Snowflake destination: HOST must be account locator only (no .snowflakecomputing.com).
# SPCS may inject SNOWFLAKE_HOST=<account>.snowflakecomputing.com — strip suffix before dlt sees it.
_dlt_snowflake_host() {
  _h="${DESTINATION__SNOWFLAKE__CREDENTIALS__HOST:-}"
  if [ -z "$_h" ]; then
    _h="${SNOWFLAKE_ACCOUNT:-${DESTINATION__SNOWFLAKE__CREDENTIALS__ACCOUNT:-}}"
  fi
  if [ -z "$_h" ] && [ -n "${SNOWFLAKE_HOST:-}" ]; then
    _h="${SNOWFLAKE_HOST}"
  fi
  _h="${_h#https://}"
  _h="${_h#http://}"
  _h="${_h%%/*}"
  case "$_h" in
    *.snowflakecomputing.com) _h="${_h%.snowflakecomputing.com}" ;;
  esac
  printf '%s' "$_h"
}

if [ -f /snowflake/session/token ]; then
  _host="$(_dlt_snowflake_host)"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__HOST="$_host"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__ACCOUNT="${SNOWFLAKE_ACCOUNT:-${DESTINATION__SNOWFLAKE__CREDENTIALS__ACCOUNT:-$_host}}"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__DATABASE="${DESTINATION_DATABASE:-${DESTINATION__SNOWFLAKE__CREDENTIALS__DATABASE:-ERP}}"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__WAREHOUSE="${DESTINATION_WAREHOUSE:-${DESTINATION__SNOWFLAKE__CREDENTIALS__WAREHOUSE:-ANALYTICS}}"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__ROLE="${DESTINATION_ROLE:-${DESTINATION__SNOWFLAKE__CREDENTIALS__ROLE:-PRD_BEXIO_ETL_OPERATOR}}"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__AUTHENTICATOR="oauth"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__TOKEN="$(cat /snowflake/session/token)"
  # Avoid dlt auto-detect using SPCS-injected FQDN in SNOWFLAKE_HOST.
  export SNOWFLAKE_HOST="$_host"
fi

DATA_DIR="${BEXIO_DATA_DIR:-/data}"
mkdir -p "${DATA_DIR}/.dlt"
ln -sfn "${DATA_DIR}/.dlt" /home/appuser/.dlt 2>/dev/null || true

REFRESH_FILE="${BEXIO_REFRESH_TOKEN_FILE:-${DATA_DIR}/bexio_refresh_token}"
export BEXIO_REFRESH_TOKEN_FILE="${REFRESH_FILE}"

if [ ! -s "${REFRESH_FILE}" ] && [ -n "${BEXIO_REFRESH_TOKEN:-}" ]; then
  umask 077
  printf '%s' "${BEXIO_REFRESH_TOKEN}" > "${REFRESH_FILE}"
fi

export PIPELINE_RUN_ID="${PIPELINE_RUN_ID:-${SNOWFLAKE_JOB_ID:-$(date -u +%Y%m%dT%H%M%SZ)}}"
export BEXIO_DLT_DESTINATION="${BEXIO_DLT_DESTINATION:-snowflake}"

MODE="${BEXIO_LOAD_MODE:-dlt}"
if [ "$MODE" = "snowpipe" ]; then
  export BEXIO_STAGE_MOUNT="${BEXIO_STAGE_MOUNT:-/snowflake-stage}"
  exec python /app/snowpipe_pipeline.py
fi

exec python /app/dlt_pipeline.py
