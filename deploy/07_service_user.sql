-- Step 7a: Create service user (USERADMIN)
USE ROLE USERADMIN;

CREATE USER IF NOT EXISTS SVC_BEXIO_ETL
  TYPE = SERVICE
  DEFAULT_ROLE = PRD_BEXIO_ETL_OPERATOR
  DEFAULT_WAREHOUSE = ANALYTICS
  COMMENT = 'Service user for bexio ETL SPCS jobs — key pair auth only';

-- Step 7b: Grant role to service user (SECURITYADMIN)
USE ROLE SECURITYADMIN;

GRANT ROLE PRD_BEXIO_ETL_OPERATOR TO USER SVC_BEXIO_ETL;

-- Step 7c: Generate key pair and assign to user using UTIL_DB procedure
-- Returns: USER_NAME, PEM_PUBLIC_KEY, DER_PUBLIC_KEY_BASE64,
--          ENCRYPTED_PEM_PRIVATE_KEY, PEM_PRIVATE_KEY, PASSPHRASE, DER_PRIVATE_KEY_BASE64
--
-- IMPORTANT: Save the private key output — you need it for the dlt Snowflake destination secret.
CALL UTIL_DB.ADMIN_TOOLS.GENERATE_AND_LOG_SERVICE_KEYS_FOR_USER('SVC_BEXIO_ETL');

-- Step 7d: Store private key as Snowflake secret for dlt Snowflake destination auth
-- After running step 7c, copy the PEM_PRIVATE_KEY from the output and run:
--
-- USE ROLE PRD_BEXIO_ETL_ADMIN;
--
-- CREATE SECRET IF NOT EXISTS ERP.PRD_SECRETS.SVC_BEXIO_ETL_PRIVATE_KEY
--   TYPE = GENERIC_STRING
--   SECRET_STRING = '<paste_PEM_PRIVATE_KEY_here>'
--   COMMENT = 'RSA private key for SVC_BEXIO_ETL — used by dlt Snowflake destination';
--
-- GRANT READ ON SECRET ERP.PRD_SECRETS.SVC_BEXIO_ETL_PRIVATE_KEY TO ROLE PRD_BEXIO_ETL_OPERATOR;
