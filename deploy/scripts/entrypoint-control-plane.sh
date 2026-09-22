#!/bin/bash
# ==============================================================================
# entrypoint-control-plane.sh
# Fetches all secrets from AWS Secrets Manager, exports them as environment
# variables, runs Alembic migrations, then exec's uvicorn.
#
# Required environment (set by docker-compose, NOT by this script):
#   AWS_REGION       — e.g. us-east-1
#   AWS_SECRET_NAME  — e.g. capsule/production/control-plane
#
# The secret in Secrets Manager should be a JSON object with these keys:
#   DATABASE_URL, JWT_SIGNING_SECRET, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET,
#   S3_ACCESS_KEY, S3_SECRET_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY,
#   GEMINI_API_KEY
# ==============================================================================

set -euo pipefail

log() { echo "[entrypoint] $*" >&2; }

# ── 1. Fetch secrets from AWS Secrets Manager ─────────────────────────────────
log "Fetching secrets from AWS Secrets Manager: ${AWS_SECRET_NAME}"

SECRET_JSON=$(aws secretsmanager get-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${AWS_SECRET_NAME}" \
    --query SecretString \
    --output text)

if [ -z "${SECRET_JSON}" ]; then
    log "ERROR: Failed to fetch secrets from AWS Secrets Manager"
    exit 1
fi

# Parse and export each key from the JSON secret
export DATABASE_URL=$(echo "${SECRET_JSON}"        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['DATABASE_URL'])")
export JWT_SIGNING_SECRET=$(echo "${SECRET_JSON}"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['JWT_SIGNING_SECRET'])")
export OIDC_CLIENT_ID=$(echo "${SECRET_JSON}"      | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('OIDC_CLIENT_ID',''))")
export OIDC_CLIENT_SECRET=$(echo "${SECRET_JSON}"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('OIDC_CLIENT_SECRET',''))")
export S3_ACCESS_KEY=$(echo "${SECRET_JSON}"       | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('S3_ACCESS_KEY',''))")
export S3_SECRET_KEY=$(echo "${SECRET_JSON}"       | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('S3_SECRET_KEY',''))")
export OPENAI_API_KEY=$(echo "${SECRET_JSON}"      | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('OPENAI_API_KEY',''))")
export ANTHROPIC_API_KEY=$(echo "${SECRET_JSON}"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ANTHROPIC_API_KEY',''))")
export GEMINI_API_KEY=$(echo "${SECRET_JSON}"      | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('GEMINI_API_KEY',''))")

log "Secrets loaded successfully"

# ── 2. Run database migrations ────────────────────────────────────────────────
log "Running Alembic migrations..."
cd /app
python -m alembic -c alembic.ini upgrade head
log "Migrations complete"

# ── 3. Exec uvicorn (replaces shell, so PID 1 = uvicorn for proper signal handling)
log "Starting uvicorn..."
exec python -m uvicorn --app-dir src main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2 \
    --access-log \
    --log-level info
