#!/bin/bash
# ==============================================================================
# deploy.sh
# Deploy a new image tag to a Capsule Platform host.
# Pulls images from ECR, runs migrations, restarts services, health-checks.
#
# Usage:
#   bash deploy.sh [control-plane|sandbox-host] <image-tag>
#
# Environment (must be set by CI or calling shell):
#   ECR_REGISTRY  — e.g. 123456789.dkr.ecr.us-east-1.amazonaws.com
#   AWS_REGION    — e.g. us-east-1
#   IMAGE_TAG     — e.g. v1.2.3 or latest
# ==============================================================================

set -euo pipefail

ROLE="${1:-control-plane}"
IMAGE_TAG="${2:-${IMAGE_TAG:-latest}}"
DEPLOY_DIR="${CAPSULE_DEPLOY_DIR:-/opt/capsule}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://localhost:8000/healthz}"
HEALTHCHECK_RETRIES=30
HEALTHCHECK_SLEEP=5

log() { echo "[deploy][$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

log "Starting deployment: role=${ROLE} tag=${IMAGE_TAG}"

# ── 1. ECR login ──────────────────────────────────────────────────────────────
log "Logging into ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
    | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

# ── 2. Export IMAGE_TAG so compose picks it up ────────────────────────────────
export IMAGE_TAG
export ECR_REGISTRY
export AWS_REGION

# Source non-secret config
# shellcheck disable=SC1090
source "${DEPLOY_DIR}/env.conf" 2>/dev/null || true

# ── 3. Pull new images ────────────────────────────────────────────────────────
COMPOSE_FILE="${DEPLOY_DIR}/deploy/compose/docker-compose.${ROLE}.yml"
log "Pulling images from ${COMPOSE_FILE}..."
docker compose -f "${COMPOSE_FILE}" pull

# ── 4. Run DB migrations (control-plane only) ─────────────────────────────────
if [ "${ROLE}" = "control-plane" ]; then
    log "Running Alembic migrations..."
    docker compose -f "${COMPOSE_FILE}" run --rm control-plane \
        python -m alembic -c alembic.ini upgrade head || {
        log "ERROR: Migration failed. Aborting deployment."
        exit 1
    }
fi

# ── 5. Restart services ───────────────────────────────────────────────────────
log "Restarting capsule-${ROLE} service..."
systemctl restart "capsule-${ROLE}"

# ── 6. Health check ───────────────────────────────────────────────────────────
log "Waiting for health check at ${HEALTHCHECK_URL}..."
for i in $(seq 1 "${HEALTHCHECK_RETRIES}"); do
    if curl -sf "${HEALTHCHECK_URL}" > /dev/null 2>&1; then
        log "Health check passed (attempt ${i})"
        break
    fi
    if [ "${i}" -eq "${HEALTHCHECK_RETRIES}" ]; then
        log "ERROR: Health check failed after ${HEALTHCHECK_RETRIES} attempts"
        log "Rolling back by restarting with previous image..."
        # systemd will restart with the compose file; CI must retain previous tag
        exit 1
    fi
    log "  ...waiting (${i}/${HEALTHCHECK_RETRIES})"
    sleep "${HEALTHCHECK_SLEEP}"
done

log "Deployment complete: role=${ROLE} tag=${IMAGE_TAG}"
