#!/bin/sh
# SPCS job entrypoint: Snowflake session token for dlt, Bexio refresh token file, then pipeline.
set -e

# dlt Snowflake destination via SPCS internal auth.
# Write a connections.toml so the Python connector uses SNOWFLAKE_HOST directly
# (dlt doesn't pass 'host' kwarg, so we configure it via the connector's config file).

if [ -f /snowflake/session/token ]; then
  _token="$(cat /snowflake/session/token)"
  _db="${DESTINATION_DATABASE:-ERP}"
  _wh="${DESTINATION_WAREHOUSE:-ANALYTICS}"
  _role="${DESTINATION_ROLE:-PRD_BEXIO_ETL_OPERATOR}"
  _schema="${BEXIO_DLT_DATASET_NAME:-PRD_BEXIO}"

  mkdir -p /home/appuser/.snowflake
  cat > /home/appuser/.snowflake/connections.toml <<TOML
[default]
host = "${SNOWFLAKE_HOST}"
account = "${SNOWFLAKE_ACCOUNT}"
authenticator = "oauth"
token = "${_token}"
database = "${_db}"
schema = "${_schema}"
warehouse = "${_wh}"
role = "${_role}"
TOML
  chmod 600 /home/appuser/.snowflake/connections.toml

  export SNOWFLAKE_DEFAULT_CONNECTION_NAME="default"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__ACCOUNT="${SNOWFLAKE_ACCOUNT}"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__DATABASE="${_db}"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__WAREHOUSE="${_wh}"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__ROLE="${_role}"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__AUTHENTICATOR="oauth"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__TOKEN="${_token}"
  export DESTINATION__SNOWFLAKE__CREDENTIALS__HOST="${SNOWFLAKE_HOST%.snowflakecomputing.com}"
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
