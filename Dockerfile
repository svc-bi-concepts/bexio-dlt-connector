FROM python:3.11-slim

# Non-root runtime (SPCS / general hardening). /app must be writable for DuckDB + dlt state if not mounted.
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app
RUN chown appuser:appuser /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bexio_oauth.py bexio_credentials.py dlt_pipeline.py loader_state.py snowflake_jwt.py snowpipe_rest.py snowpipe_pipeline.py .
COPY spcs/entrypoint.sh /app/spcs/entrypoint.sh
RUN chmod +x /app/spcs/entrypoint.sh

USER appuser

CMD ["python", "dlt_pipeline.py"]
