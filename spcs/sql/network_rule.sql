-- Egress to Bexio API and OAuth token endpoint.
-- Run via: spcs/deploy_infra.sh --env <env>

USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE NETWORK RULE ${DB_NAME}.${SCHEMA}.BEXIO_API_RULE
  TYPE       = HOST_PORT
  MODE       = EGRESS
  VALUE_LIST = ('api.bexio.com:443', 'auth.bexio.com:443')
  COMMENT    = 'Bexio REST API + OIDC token endpoint for bexio-dlt-connector';

GRANT USAGE ON NETWORK RULE ${DB_NAME}.${SCHEMA}.BEXIO_API_RULE TO ROLE ${DEPLOYER_ROLE};
GRANT USAGE ON NETWORK RULE ${DB_NAME}.${SCHEMA}.BEXIO_API_RULE TO ROLE ${OPERATOR_ROLE};
