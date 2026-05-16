USE ROLE PRD_BEXIO_ETL_OPERATOR;

EXECUTE JOB SERVICE
  IN COMPUTE POOL PRD_BEXIO_COMPUTE_POOL
  NAME = ERP.PRD_INFRA.BEXIO_ETL_MANUAL_RUN
  EXTERNAL_ACCESS_INTEGRATIONS = (BEXIO_ETL_EAI)
  QUERY_WAREHOUSE = ANALYTICS
  FROM SPECIFICATION $$
spec:
  containers:
  - name: bexio-etl
    image: /ERP/PRD_INFRA/BEXIO_IMAGES/bexio-dlt-connector:v1.0
    env:
      BEXIO_DLT_DESTINATION: snowflake
      BEXIO_DLT_DATASET_NAME: PRD_BEXIO
      BEXIO_DLT_PIPELINE_NAME: bexio_pipeline
    secrets:
    - snowflakeSecret:
        objectName: ERP.PRD_SECRETS.BEXIO_CLIENT_ID
      secretKeyRef: secret_string
      envVarName: BEXIO_CLIENT_ID
    - snowflakeSecret:
        objectName: ERP.PRD_SECRETS.BEXIO_CLIENT_SECRET
      secretKeyRef: secret_string
      envVarName: BEXIO_CLIENT_SECRET
    - snowflakeSecret:
        objectName: ERP.PRD_SECRETS.BEXIO_REFRESH_TOKEN
      secretKeyRef: secret_string
      envVarName: BEXIO_REFRESH_TOKEN
    resources:
      requests:
        memory: 1Gi
        cpu: 0.5
      limits:
        memory: 2Gi
        cpu: 1
  logExporters:
    eventTableConfig:
      logLevel: INFO
  $$;
