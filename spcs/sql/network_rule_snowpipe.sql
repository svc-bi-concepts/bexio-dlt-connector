-- Egress: Bexio + Snowflake REST (Snowpipe insertFiles from SPCS).
-- Set SNOWFLAKE_EGRESS_HOSTPORT in spcs/config/<env>.env, e.g.
--   xy12345.eu-central-1.aws.snowflakecomputing.com:443
-- (no https:// prefix)

USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE NETWORK RULE ${DB_NAME}.${SCHEMA}.BEXIO_API_RULE
  TYPE       = HOST_PORT
  MODE       = EGRESS
  VALUE_LIST = (
    'api.bexio.com:443',
    'auth.bexio.com:443',
    '${SNOWFLAKE_EGRESS_HOSTPORT}'
  )
  COMMENT    = 'Bexio API + OAuth + Snowflake REST (Snowpipe) for bexio-connector';

GRANT USAGE ON NETWORK RULE ${DB_NAME}.${SCHEMA}.BEXIO_API_RULE TO ROLE ${DEPLOYER_ROLE};
GRANT USAGE ON NETWORK RULE ${DB_NAME}.${SCHEMA}.BEXIO_API_RULE TO ROLE ${OPERATOR_ROLE};
