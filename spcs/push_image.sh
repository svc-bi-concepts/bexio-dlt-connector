#!/usr/bin/env bash
# Build and push bexio-dlt-connector image to Snowflake image repository.
#
# Usage:
#   ./spcs/push_image.sh --env dev

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
ENV_NAME="dev"
CONNECTION_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --connection|-c) CONNECTION_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

set -a && source "${SCRIPT_DIR}/config/${ENV_NAME}.env" && set +a
CONNECTION="${CONNECTION_OVERRIDE:-${SNOW_CONNECTION:-bexio-dlt}}"

if ! command -v docker &>/dev/null; then
  echo "ERROR: Docker is required." >&2
  exit 1
fi

REGISTRY=$(snow spcs image-registry url -c "$CONNECTION")
IMAGE="${REGISTRY}/${DB_NAME_LOWER}/${SCHEMA_LOWER}/${IMAGE_REPO}/connector:${ENV}-latest"

echo "→ Logging in to ${REGISTRY}"
snow spcs image-registry login -c "$CONNECTION"

echo "→ Building ${IMAGE}"
docker build --platform linux/amd64 -t "${IMAGE}" "${REPO_ROOT}"

echo "→ Pushing ${IMAGE}"
docker push "${IMAGE}"

echo "✓ Image pushed."
echo "  Next: ./spcs/deploy_infra.sh --env ${ENV_NAME}"
echo "        ./spcs/deploy_job.sh --env ${ENV_NAME}"
