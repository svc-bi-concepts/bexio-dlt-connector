# bexio-dlt-connector

Bexio REST API → [dlt](https://dlthub.com/) with **OAuth**, flattened entities, and **PSA-style SCD2** loads to **DuckDB** or **Snowflake**.

This repository continues the connector work previously kept under `ft_customconnector_bexio` (local folder `FT_CustomConnector_Bexio`). Use **this** repo name for new Git remotes and Docker image tags.

---

```mermaid
sequenceDiagram
    participant Pipeline as dlt pipeline
    participant State as Pagination / offset
    participant API as Bexio API

    Note over Pipeline,API: Initial State: {offset: 0, has_more: 1}

    Pipeline->>API: Request Data (offset: 0)
    API-->>Pipeline: Return 2000 Records
    Pipeline->>State: Update State with 2000 records
    State-->>Pipeline: has_more: 1, offset: 2000

    Note over Pipeline,API: Scenario 1: Full Batch Returned

    Pipeline->>API: Request Data (offset: 2000)
    API-->>Pipeline: Return 2000 Records
    Pipeline->>State: Update State with 2000 records
    State-->>Pipeline: has_more: 1, offset: 4000

    Note over Pipeline,API: Scenario 2: Partial Batch Returned

    Pipeline->>API: Request Data (offset: 4000)
    API-->>Pipeline: Return 156 Records
    Pipeline->>State: Update State with 156 records
    State-->>Pipeline: has_more: 0, offset: 4156

    Note over Pipeline,API: Scenario 3: No More Data

    Pipeline->>API: Request Data (offset: 4156)
    API-->>Pipeline: Return 0 Records
    Pipeline->>State: Update State with 0 records
    State-->>Pipeline: has_more: 0, offset: 4156 (Reset or halt fetching)

    Note over Pipeline,API: Vulnerability Analysis

```

For **OAuth, refresh rotation, and env vars**, see [AUTHENTICATION.md](AUTHENTICATION.md).

**Local checks (no API):** `pip install -r requirements-dev.txt && pytest`

## Run with dlt in Docker

1. Ensure `.env` has OAuth: `BEXIO_CLIENT_ID`, `BEXIO_CLIENT_SECRET`, and `BEXIO_REFRESH_TOKEN` or `BEXIO_REFRESH_TOKEN_FILE` (from `python oauth_login.py`). PATs are not used.
2. Build the container:
   `docker build -t bexio-dlt-connector .`
3. Run the pipeline. Mount `.dlt` for dlt state (image runs as `appuser`; home is `/home/appuser`). For **automatic refresh-token rotation**, use a writable file mount (create the host file once: `touch bexio_refresh_token`):
   `docker run --rm --env-file .env -v "$(pwd)/.dlt:/home/appuser/.dlt" -e BEXIO_REFRESH_TOKEN_FILE=/run/bexio/refresh_token -v "$(pwd)/bexio_refresh_token:/run/bexio/refresh_token" bexio-dlt-connector`
   Omit the refresh file mount if you only use env-based `BEXIO_REFRESH_TOKEN` (IdP rotation may then require updating the secret store yourself).

The pipeline writes data with `dlt` using **PSA SCD2** (`merge` + `scd2` + `row_hash` excluding `_loaded_at` / `_extract_run_id`). Default destination is **DuckDB**; set `BEXIO_DLT_DESTINATION=snowflake` for Snowflake (see [dlt Snowflake](https://dlthub.com/docs/dlt-ecosystem/destinations/snowflake)). Dataset defaults to `bexio` (`BEXIO_DLT_DATASET_NAME`).






```mermaid
sequenceDiagram
    participant Bexio
    participant 4.0

    4.0->>Bexio: Fetch data
    Bexio-->>4.0: Return data, current page and page count
    Note over 4.0: Check if current page == page count
    alt current page == page count
        4.0->>4.0: Set needs_update to 0
    else current page < page count
        4.0->>4.0: Add 1 to page for the next call
    end



    participant 3.0
    participant Bexio
    3.0->>Bexio: Fetch data
    Bexio-->>3.0: Return data, X-Total_count and X-Offset
    Note over 3.0: Calculate residual_ids (X-Total_count - X-Offset)
    alt residual_ids > 0
        3.0->>3.0: Set needs_update to 1
    else residual_ids <= 0
        3.0->>3.0: Set needs_update to 0
    end


    participant 2.0a
    participant Bexio
    2.0a->>Bexio: Fetch data
    Bexio-->>2.0a: Return data and rate_limit
    Note over 2.0a: Check if count of fetched data == rate_limit
    alt count of fetched data == rate_limit
        2.0a->>2.0a: Set needs_update to 1
    else count of fetched data < rate_limit
        2.0a->>2.0a: Set needs_update to 0
    end

    participant 2.0
    participant Bexio
    2.0->>Bexio: Fetch data
    Bexio-->>2.0: Return data and rate_limit
    Note over 2.0: Check if count of fetched data == rate_limit
    alt count of fetched data == rate_limit
        2.0->>2.0: Set needs_update to 1
    else count of fetched data < rate_limit
        2.0->>2.0: Set needs_update to 0
    end

```