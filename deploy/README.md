# bexio-dlt-connector — Snowflake SPCS Deployment

## Prerequisites

- Snowflake system roles: USERADMIN, SECURITYADMIN, SYSADMIN, ACCOUNTADMIN
- Docker installed locally (for image build & push)
- Snowflake CLI (`snow`) installed (for image registry login)
- Bexio OAuth credentials (client ID, client secret, refresh token)

## Role Usage (Snowflake best practices)

| System Role | Used For |
|-------------|----------|
| **USERADMIN** | Create custom roles and service users |
| **SECURITYADMIN** | Grant privileges (MANAGE GRANTS) |
| **SYSADMIN** | Create database, transfer schema ownership |
| **ACCOUNTADMIN** | Compute pool, External Access Integration (account-level) |
| **PRD_BEXIO_ETL_ADMIN** | Schemas (owner), image repo, secrets, network rules |
| **PRD_BEXIO_ETL_OPERATOR** | Execute jobs, create stages/tasks |

## Execution Order

Run scripts sequentially in a Snowflake worksheet:

| Step | Script | Role(s) | Description |
|------|--------|---------|-------------|
| 1 | `01_roles.sql` | USERADMIN + SECURITYADMIN + ACCOUNTADMIN | Create RBAC hierarchy + account grants |
| 2 | `02_database_schemas.sql` | SYSADMIN | Create ERP database + PRD_* schemas, transfer ownership |
| 3 | `03_governance.sql` | SECURITYADMIN | Future grants for DATA_READER and OPERATOR |
| 4 | `04_network_rule.sql` | PRD_BEXIO_ETL_ADMIN | Network egress rule |
| 5 | `05_compute_pool.sql` | ACCOUNTADMIN | Create compute pool + grants |
| 6 | `06_image_repo.sql` | PRD_BEXIO_ETL_ADMIN | Create image repository |
| 7 | `07_service_user.sql` | USERADMIN + SECURITYADMIN | Create SVC_BEXIO_ETL + key pair |
| — | **Snowflake CLI setup** | (local machine) | See below |
| — | **Docker build & push** | (local machine) | See below |
| 8 | `08_secrets.sql` | PRD_BEXIO_ETL_ADMIN | Create secrets (replace placeholders!) |
| 9 | `09_eai.sql` | ACCOUNTADMIN | External Access Integration (needs secrets) |
| 10 | `10_execute_job.sql` | PRD_BEXIO_ETL_OPERATOR | Manual test run |
| 11 | `11_schedule_task.sql` | PRD_BEXIO_ETL_OPERATOR | Daily CRON schedule |

## Snowflake CLI — Service User Connection

After step 7, configure the CLI connection for `SVC_BEXIO_ETL`:

```bash
snow connection add \
  --connection-name bexio-etl-prd \
  --account es10286-marketplace \
  --user SVC_BEXIO_ETL \
  --authenticator SNOWFLAKE_JWT \
  --private-key-file "/full/path/to/svc_bexio_etl_rsa_key.p8" \
  --role PRD_BEXIO_ETL_OPERATOR \
  --warehouse ANALYTICS \
  --database ERP \
  --schema PRD_INFRA
```

## Docker Build & Push

```bash
snow spcs image-registry login --connection bexio-etl-prd

docker build --rm --platform linux/amd64 \
  -t es10286-marketplace.registry.snowflakecomputing.com/erp/prd_infra/bexio_images/bexio-dlt-connector:v1.0 .

docker push es10286-marketplace.registry.snowflakecomputing.com/erp/prd_infra/bexio_images/bexio-dlt-connector:v1.0
```

## Upload Job Spec to Stage (before step 11)

```sql
USE ROLE PRD_BEXIO_ETL_OPERATOR;
PUT file://deploy/07_job_spec.yaml @ERP.PRD_INFRA.BEXIO_SPECS AUTO_COMPRESS=FALSE;
```

## Post-Deployment

1. **Verify manual run**: `DESCRIBE SERVICE ERP.PRD_INFRA.BEXIO_ETL_MANUAL_RUN`
2. **Check logs**: Query your account event table for container logs
3. **Monitor task**: `SELECT * FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY()) WHERE NAME = 'BEXIO_DAILY_ETL'`

## Secret Rotation

After bexio rotates the refresh token, update the secret:

```sql
USE ROLE PRD_BEXIO_ETL_ADMIN;
ALTER SECRET ERP.PRD_SECRETS.BEXIO_REFRESH_TOKEN
  SET SECRET_STRING = '<new_refresh_token>';
```
