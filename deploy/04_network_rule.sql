USE ROLE PRD_BEXIO_ETL_ADMIN;

CREATE OR REPLACE NETWORK RULE ERP.PRD_INFRA.BEXIO_EGRESS_RULE
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('api.bexio.com', 'auth.bexio.com')
  COMMENT = 'Allow egress to bexio API and OAuth token endpoint only';
