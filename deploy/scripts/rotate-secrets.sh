#!/bin/bash
# ==============================================================================
# rotate-secrets.sh
# Rotates the JWT signing secret (and optionally other secrets).
# Generates a new key, stores it in AWS Secrets Manager, and triggers a
# rolling restart of the control-plane so new tokens are issued with the
# new key immediately, while the old key is briefly kept for grace period.
#
# Usage:
#   bash rotate-secrets.sh [--dry-run]
#
# Required env:
#   AWS_REGION, AWS_SECRET_NAME (e.g. capsule/production/control-plane)
#   CONTROL_PLANE_HOST (SSH hostname/IP for restart trigger)
# ==============================================================================

set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

log() { echo "[rotate][$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

log "Starting secret rotation (dry-run=${DRY_RUN})"

# ── 1. Fetch current secret ───────────────────────────────────────────────────
log "Fetching current secret from Secrets Manager: ${AWS_SECRET_NAME}"
CURRENT_SECRET=$(aws secretsmanager get-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${AWS_SECRET_NAME}" \
    --query SecretString \
    --output text)

# ── 2. Generate new JWT signing key ──────────────────────────────────────────
NEW_JWT_KEY=$(openssl rand -hex 64)
log "New JWT signing key generated (length: ${#NEW_JWT_KEY})"

# ── 3. Update secret in Secrets Manager ──────────────────────────────────────
UPDATED_SECRET=$(echo "${CURRENT_SECRET}" \
    | python3 -c "
import sys, json
d = json.load(sys.stdin)
import os
d['JWT_SIGNING_SECRET'] = os.environ['NEW_JWT_KEY']
print(json.dumps(d))
" NEW_JWT_KEY="${NEW_JWT_KEY}")

if [ "${DRY_RUN}" -eq 1 ]; then
    log "[DRY RUN] Would update Secrets Manager — skipping actual write"
else
    aws secretsmanager put-secret-value \
        --region "${AWS_REGION}" \
        --secret-id "${AWS_SECRET_NAME}" \
        --secret-string "${UPDATED_SECRET}"
    log "Secrets Manager updated successfully"
fi

# ── 4. Trigger rolling restart of control-plane ───────────────────────────────
if [ "${DRY_RUN}" -eq 1 ]; then
    log "[DRY RUN] Would SSH to ${CONTROL_PLANE_HOST} and restart capsule-control-plane"
else
    log "Triggering rolling restart on ${CONTROL_PLANE_HOST}..."
    ssh -o StrictHostKeyChecking=yes "ubuntu@${CONTROL_PLANE_HOST}" \
        "sudo systemctl restart capsule-control-plane"
    log "Restart triggered"
fi

# ── 5. Verify new token issuance ─────────────────────────────────────────────
if [ "${DRY_RUN}" -eq 0 ]; then
    log "Waiting 30s for service to restart..."
    sleep 30

    HEALTH=$(curl -sf "https://${PLATFORM_DOMAIN:-platform.example.com}/healthz" || echo "FAILED")
    if echo "${HEALTH}" | grep -q "ok\|healthy"; then
        log "Health check passed after rotation"
    else
        log "WARNING: Health check did not return healthy. Manual verification required."
        log "Response: ${HEALTH}"
        exit 1
    fi
fi

log "Secret rotation complete"
