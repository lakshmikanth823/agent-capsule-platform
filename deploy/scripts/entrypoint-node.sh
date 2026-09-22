#!/bin/bash
# ==============================================================================
# entrypoint-node.sh
# Generic entrypoint for Node.js services (edge-proxy, egress-proxy, builder).
# Fetches secrets from AWS Secrets Manager and exports as env vars.
#
# Required env (set by docker-compose):
#   AWS_REGION, AWS_SECRET_NAME
#   SERVICE_CMD  — e.g. "node dist/index.js"
# ==============================================================================

set -euo pipefail

log() { echo "[entrypoint] $*" >&2; }

log "Fetching secrets: ${AWS_SECRET_NAME}"

SECRET_JSON=$(aws secretsmanager get-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${AWS_SECRET_NAME}" \
    --query SecretString \
    --output text)

# Export secrets as environment variables for the Node.js process
export CONTROL_PLANE_API_KEY=$(echo "${SECRET_JSON}" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); process.stdout.write(d.CONTROL_PLANE_API_KEY||'');")
export INTERNAL_SIGNING_SECRET=$(echo "${SECRET_JSON}" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); process.stdout.write(d.JWT_SIGNING_SECRET||'');")

log "Secrets loaded. Starting: ${SERVICE_CMD}"
exec ${SERVICE_CMD}
