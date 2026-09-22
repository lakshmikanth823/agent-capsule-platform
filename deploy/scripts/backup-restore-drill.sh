#!/bin/bash
# ==============================================================================
# backup-restore-drill.sh
# Validates that backup and restore procedures work correctly.
# Runs in CI or manually as a periodic operational drill.
#
# Tests:
#   1. RDS automated backup — initiates a point-in-time restore to a temp instance,
#      verifies connectivity and schema integrity, then deletes the temp instance.
#   2. S3 bundle integrity — copies a test bundle to a scratch prefix and verifies
#      SHA-256 checksum.
#
# Usage:
#   bash backup-restore-drill.sh
#
# Required env:
#   AWS_REGION, RDS_INSTANCE_ID, RDS_RESTORE_SUBNET_GROUP,
#   RDS_RESTORE_SECURITY_GROUP, S3_BUCKET, S3_TEST_OBJECT_KEY
# ==============================================================================

set -euo pipefail

log()  { echo "[drill][$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
pass() { echo "[drill][PASS] $*"; }
fail() { echo "[drill][FAIL] $*" >&2; DRILL_FAILED=1; }

DRILL_FAILED=0
RESTORE_INSTANCE_ID="capsule-drill-restore-$(date +%s)"
RESTORE_TIMEOUT=600   # seconds to wait for RDS restore

# ── 1. RDS Point-in-Time Restore ─────────────────────────────────────────────
log "Starting RDS point-in-time restore drill..."
log "Source instance: ${RDS_INSTANCE_ID}"
log "Temporary restore instance: ${RESTORE_INSTANCE_ID}"

# Restore to 5 minutes ago
RESTORE_TIME=$(date -u -d "5 minutes ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
    || date -u -v-5M +%Y-%m-%dT%H:%M:%SZ)   # macOS fallback

aws rds restore-db-instance-to-point-in-time \
    --source-db-instance-identifier "${RDS_INSTANCE_ID}" \
    --target-db-instance-identifier "${RESTORE_INSTANCE_ID}" \
    --restore-time "${RESTORE_TIME}" \
    --db-subnet-group-name "${RDS_RESTORE_SUBNET_GROUP}" \
    --vpc-security-group-ids "${RDS_RESTORE_SECURITY_GROUP}" \
    --no-publicly-accessible \
    --region "${AWS_REGION}" \
    --output text > /dev/null

log "Waiting for restore instance to become available (timeout: ${RESTORE_TIMEOUT}s)..."
ELAPSED=0
while true; do
    STATUS=$(aws rds describe-db-instances \
        --db-instance-identifier "${RESTORE_INSTANCE_ID}" \
        --region "${AWS_REGION}" \
        --query 'DBInstances[0].DBInstanceStatus' \
        --output text)
    log "  Status: ${STATUS} (${ELAPSED}s elapsed)"

    if [ "${STATUS}" = "available" ]; then
        pass "RDS restore instance is available"
        break
    fi

    if [ "${ELAPSED}" -ge "${RESTORE_TIMEOUT}" ]; then
        fail "RDS restore timed out after ${RESTORE_TIMEOUT}s"
        break
    fi

    sleep 30
    ELAPSED=$((ELAPSED + 30))
done

# Verify schema — connect and check that key tables exist
if [ "${STATUS}" = "available" ]; then
    RESTORE_ENDPOINT=$(aws rds describe-db-instances \
        --db-instance-identifier "${RESTORE_INSTANCE_ID}" \
        --region "${AWS_REGION}" \
        --query 'DBInstances[0].Endpoint.Address' \
        --output text)
    log "Restore endpoint: ${RESTORE_ENDPOINT}"

    # Use psql to verify tables exist (password from Secrets Manager)
    RDS_PASSWORD=$(aws secretsmanager get-secret-value \
        --region "${AWS_REGION}" \
        --secret-id "${AWS_SECRET_NAME:-capsule/production/control-plane}" \
        --query SecretString --output text \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['DATABASE_PASSWORD'])")

    TABLE_COUNT=$(PGPASSWORD="${RDS_PASSWORD}" psql \
        -h "${RESTORE_ENDPOINT}" \
        -U capsule_user \
        -d capsule_control \
        -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d ' ')

    if [ "${TABLE_COUNT:-0}" -gt 0 ]; then
        pass "Schema verified: ${TABLE_COUNT} public tables found in restored instance"
    else
        fail "Schema verification failed: no tables found in restored instance"
    fi
fi

# Always delete the temporary restore instance
log "Deleting temporary restore instance..."
aws rds delete-db-instance \
    --db-instance-identifier "${RESTORE_INSTANCE_ID}" \
    --skip-final-snapshot \
    --region "${AWS_REGION}" \
    --output text > /dev/null
log "Temporary instance deletion initiated"

# ── 2. S3 Bundle Integrity ────────────────────────────────────────────────────
log "Starting S3 bundle integrity drill..."

SCRATCH_KEY="drill-scratch/$(date +%s)-test-bundle.tar.gz"

# Get the test object (the key must be an existing real bundle)
log "Copying test bundle to scratch prefix: s3://${S3_BUCKET}/${SCRATCH_KEY}"
aws s3 cp "s3://${S3_BUCKET}/${S3_TEST_OBJECT_KEY}" /tmp/drill-bundle.tar.gz \
    --region "${AWS_REGION}"

# Compute checksum
ORIGINAL_HASH=$(sha256sum /tmp/drill-bundle.tar.gz | awk '{print $1}')
log "Original SHA-256: ${ORIGINAL_HASH}"

# Upload to scratch
aws s3 cp /tmp/drill-bundle.tar.gz "s3://${S3_BUCKET}/${SCRATCH_KEY}" \
    --region "${AWS_REGION}"

# Download from scratch and verify
aws s3 cp "s3://${S3_BUCKET}/${SCRATCH_KEY}" /tmp/drill-bundle-verify.tar.gz \
    --region "${AWS_REGION}"

VERIFY_HASH=$(sha256sum /tmp/drill-bundle-verify.tar.gz | awk '{print $1}')
log "Verified SHA-256: ${VERIFY_HASH}"

if [ "${ORIGINAL_HASH}" = "${VERIFY_HASH}" ]; then
    pass "S3 bundle integrity verified (SHA-256 matches)"
else
    fail "S3 bundle integrity FAILED (hashes differ: ${ORIGINAL_HASH} != ${VERIFY_HASH})"
fi

# Clean up scratch
aws s3 rm "s3://${S3_BUCKET}/${SCRATCH_KEY}" --region "${AWS_REGION}"
rm -f /tmp/drill-bundle.tar.gz /tmp/drill-bundle-verify.tar.gz

# ── Final Result ──────────────────────────────────────────────────────────────
echo ""
if [ "${DRILL_FAILED}" -eq 0 ]; then
    echo "=============================================="
    echo " DRILL PASSED: RDS restore OK, S3 bundle OK"
    echo " $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "=============================================="
    exit 0
else
    echo "=============================================="
    echo " DRILL FAILED — see errors above"
    echo " $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "=============================================="
    exit 1
fi
