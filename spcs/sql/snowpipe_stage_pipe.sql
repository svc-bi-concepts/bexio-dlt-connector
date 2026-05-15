-- Stage + landing table + Snowpipe for NDJSON envelopes written by snowpipe_pipeline.py
-- Render with envsubst using spcs/config/<env>.env:
--   set -a && source spcs/config/dev.env && set +a
--   export DEPLOYER_ROLE DATA_SCHEMA
--   envsubst < spcs/sql/snowpipe_stage_pipe.sql | snow sql -c <conn>

USE ROLE ${DEPLOYER_ROLE};

CREATE SCHEMA IF NOT EXISTS ${DB_NAME}.${SCHEMA};
CREATE SCHEMA IF NOT EXISTS ${DB_NAME}.${DATA_SCHEMA};

CREATE STAGE IF NOT EXISTS ${DB_NAME}.${SCHEMA}.BEXIO_INGEST_STAGE
  DIRECTORY = (ENABLE = TRUE)
  COMMENT = 'NDJSON batches from bexio-dlt SPCS (snowpipe mode)';

CREATE TABLE IF NOT EXISTS ${DB_NAME}.${DATA_SCHEMA}.BEXIO_PIPE_LANDING (
  META_FILENAME   STRING,
  META_SCAN_TIME  TIMESTAMP_LTZ,
  EXTRACT_RUN_ID  STRING,
  LOADED_AT       TIMESTAMP_TZ,
  RESOURCE_NAME   STRING,
  PAYLOAD         VARIANT
)
COMMENT = 'One row per NDJSON line; payload holds flattened Bexio entity + lineage columns';

CREATE OR REPLACE PIPE ${DB_NAME}.${SCHEMA}.BEXIO_JSON_PIPE
  AUTO_INGEST = FALSE
  COMMENT = 'Loads envelopes {_extract_run_id,_loaded_at,_resource,payload} from internal stage'
  AS
  COPY INTO ${DB_NAME}.${DATA_SCHEMA}.BEXIO_PIPE_LANDING (
    META_FILENAME,
    META_SCAN_TIME,
    EXTRACT_RUN_ID,
    LOADED_AT,
    RESOURCE_NAME,
    PAYLOAD
  )
  FROM (
    SELECT
      METADATA$FILENAME,
      METADATA$START_SCAN_TIME,
      $1:_extract_run_id::STRING,
      $1:_loaded_at::TIMESTAMP_TZ,
      $1:_resource::STRING,
      $1:payload::VARIANT
    FROM @${DB_NAME}.${SCHEMA}.BEXIO_INGEST_STAGE
  )
  FILE_FORMAT = (TYPE = JSON);

GRANT USAGE ON SCHEMA ${DB_NAME}.${SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT READ ON STAGE ${DB_NAME}.${SCHEMA}.BEXIO_INGEST_STAGE TO ROLE ${DEPLOYER_ROLE};
GRANT USAGE ON SCHEMA ${DB_NAME}.${DATA_SCHEMA} TO ROLE ${DEPLOYER_ROLE};
GRANT INSERT ON TABLE ${DB_NAME}.${DATA_SCHEMA}.BEXIO_PIPE_LANDING TO ROLE ${DEPLOYER_ROLE};
