USE ROLE PRD_BEXIO_ETL_ADMIN;

CREATE IMAGE REPOSITORY IF NOT EXISTS ERP.PRD_INFRA.BEXIO_IMAGES
  COMMENT = 'OCI image repository for bexio-dlt-connector';

GRANT READ  ON IMAGE REPOSITORY ERP.PRD_INFRA.BEXIO_IMAGES TO ROLE PRD_BEXIO_ETL_OPERATOR;
GRANT WRITE ON IMAGE REPOSITORY ERP.PRD_INFRA.BEXIO_IMAGES TO ROLE PRD_BEXIO_ETL_OPERATOR;

SHOW IMAGE REPOSITORIES IN SCHEMA ERP.PRD_INFRA;
-- Note the repository_url from output.  Use it to build and push:
--
--   snow spcs image-registry login
--   docker build --rm --platform linux/amd64 -t <repository_url>/bexio-dlt-connector:v1.0 .
--   docker push <repository_url>/bexio-dlt-connector:v1.0
