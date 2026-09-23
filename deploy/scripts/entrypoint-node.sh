#!/bin/bash
# ==============================================================================
# entrypoint-node.sh
# Generic entrypoint for Node.js services (edge-proxy, egress-proxy, builder, sandbox-runner).
# Fetches secrets from AWS Secrets Manager when AWS_SECRET_NAME is provided
# and exports them as environment variables.
# ==============================================================================

set -euo pipefail

log() { echo "[entrypoint][$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >&2; }

if [ -n "${AWS_SECRET_NAME:-}" ]; then
    log "Fetching secrets from AWS Secrets Manager: ${AWS_SECRET_NAME} (region: ${AWS_REGION:-us-east-1})"

    SECRET_JSON=$(aws secretsmanager get-secret-value \
        --region "${AWS_REGION:-us-east-1}" \
        --secret-id "${AWS_SECRET_NAME}" \
        --query SecretString \
        --output text)

    if [ -n "${SECRET_JSON}" ]; then
        # Export secrets for Node.js services (edge-proxy, egress-proxy, builder, sandbox-runner)
        export IDENTITY_SIGNING_KEY=$(echo "${SECRET_JSON}" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); process.stdout.write(d.IDENTITY_SIGNING_KEY||d.JWT_SIGNING_SECRET||'');")
        export SESSION_SECRET=$(echo "${SECRET_JSON}" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); process.stdout.write(d.SESSION_SECRET||'');")
        export CONTROL_PLANE_SERVICE_TOKEN=$(echo "${SECRET_JSON}" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); process.stdout.write(d.CONTROL_PLANE_SERVICE_TOKEN||d.CONTROL_PLANE_API_KEY||'');")
        export RUNNER_SHARED_SECRET=$(echo "${SECRET_JSON}" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); process.stdout.write(d.RUNNER_SHARED_SECRET||'');")
        export CONTROL_PLANE_API_KEY=$(echo "${SECRET_JSON}" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); process.stdout.write(d.CONTROL_PLANE_API_KEY||'');")
        export INTERNAL_SIGNING_SECRET=$(echo "${SECRET_JSON}" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); process.stdout.write(d.JWT_SIGNING_SECRET||'');")
        log "Secrets successfully loaded and exported."
    else
        log "WARNING: Secrets Manager returned empty secret."
    fi
else
    log "No AWS_SECRET_NAME provided. Proceeding with existing environment."
fi

# If arguments were passed to the entrypoint, execute them; otherwise default to SERVICE_CMD or node dist/index.js
if [ $# -gt 0 ]; then
    exec "$@"
elif [ -n "${SERVICE_CMD:-}" ]; then
    exec ${SERVICE_CMD}
else
    exec node dist/index.js
fi
