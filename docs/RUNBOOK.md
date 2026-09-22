# Capsule Platform — Runbook

**Version:** 1.0  
**Last Updated:** 2026-09-22  
**Audience:** Platform operators and on-call engineers  

> [!IMPORTANT]
> This runbook assumes the platform is deployed on AWS with Docker Compose + systemd + gVisor on Ubuntu 24.04 LTS EC2 instances. See [docs/TRD.md](./TRD.md) for architecture and [SANDBOX_RUNBOOK.md](./SANDBOX_RUNBOOK.md) for sandbox-specific procedures.

---

## Table of Contents

1. [Prerequisites & Access](#1-prerequisites--access)
2. [Initial Deployment (Fresh Environment)](#2-initial-deployment-fresh-environment)
3. [Standard Deploy (Code Update)](#3-standard-deploy-code-update)
4. [Platform Rollback](#4-platform-rollback)
5. [Restore from Backup](#5-restore-from-backup)
6. [Key Rotation](#6-key-rotation)
7. [Kill Switch — Incident Response](#7-kill-switch--incident-response)
8. [Monitoring & Alerting](#8-monitoring--alerting)
9. [Backup Restore Drill Results](#9-backup-restore-drill-results)
10. [Human Task Checklist](#10-human-task-checklist)

---

## 1. Prerequisites & Access

### Required tools on operator workstation
```bash
# AWS CLI v2
aws --version  # >= 2.15

# SSH key (ed25519 recommended)
# Fingerprint registered in AWS EC2 Key Pairs
```

### EC2 instance inventory

| Role | AWS Name Tag | Internal IP | SSH User |
|---|---|---|---|
| Control Plane | `capsule-control-plane` | 10.0.1.10 | ubuntu |
| Sandbox Host 1 | `capsule-sandbox-01` | 10.0.2.10 | ubuntu |
| Edge / nginx | Runs on control-plane VM | — | — |

### AWS Secrets Manager paths

| Secret | Path |
|---|---|
| Control Plane secrets | `capsule/production/control-plane` |
| Sandbox Host secrets | `capsule/production/sandbox-host` |

---

## 2. Initial Deployment (Fresh Environment)

> [!IMPORTANT]
> Complete all [human tasks](#10-human-task-checklist) (DNS, PSL, ACM, GitHub secrets) before running this procedure.

### Step 1 — Provision EC2 instances

Launch two Ubuntu 24.04 LTS instances on AWS:
- **Control Plane**: t3.medium, 30GB root EBS gp3, in the platform VPC
- **Sandbox Host**: t3.medium, 50GB root EBS gp3 (extra space for container images), same VPC

Assign an IAM Instance Profile to each EC2 with permissions:
- `secretsmanager:GetSecretValue` for its own secret path
- `s3:*` on the `capsule-artifacts-*` bucket prefix
- `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` (for CloudWatch logging driver)

### Step 2 — Bootstrap each EC2

```bash
# Clone the repo to /opt/capsule on each EC2
git clone https://github.com/your-org/capsule-platform.git /opt/capsule

# Bootstrap control-plane VM
sudo bash /opt/capsule/deploy/scripts/bootstrap-ec2.sh control-plane

# Bootstrap sandbox-host VM  
sudo bash /opt/capsule/deploy/scripts/bootstrap-ec2.sh sandbox-host
```

### Step 3 — Populate env.conf (non-secret config)

Create `/opt/capsule/env.conf` on **each host** (this file has no secrets):

```bash
# /opt/capsule/env.conf  — committed per-environment, no secrets
AWS_REGION=us-east-1
ECR_REGISTRY=123456789.dkr.ecr.us-east-1.amazonaws.com
IMAGE_TAG=latest
CP_SECRET_NAME=capsule/production/control-plane
SH_SECRET_NAME=capsule/production/sandbox-host
S3_BUCKET=capsule-artifacts-prod
APP_BASE_DOMAIN=apps.example.com
PLATFORM_DOMAIN=platform.example.com
CONTROL_PLANE_INTERNAL_IP=10.0.1.10
```

### Step 4 — Populate AWS Secrets Manager

```bash
# Create the control-plane secret (replace all values)
aws secretsmanager create-secret \
  --region us-east-1 \
  --name capsule/production/control-plane \
  --secret-string '{
    "DATABASE_URL": "postgresql+asyncpg://capsule_user:CHANGEME@your-rds-endpoint.us-east-1.rds.amazonaws.com:5432/capsule_control",
    "DATABASE_PASSWORD": "CHANGEME",
    "JWT_SIGNING_SECRET": "'$(openssl rand -hex 64)'",
    "OIDC_CLIENT_ID": "your-oidc-client-id",
    "OIDC_CLIENT_SECRET": "your-oidc-client-secret",
    "S3_ACCESS_KEY": "",
    "S3_SECRET_KEY": "",
    "OPENAI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "GEMINI_API_KEY": ""
  }'
# Note: S3_ACCESS_KEY/SECRET_KEY are empty when using IAM Instance Profile for S3 access
```

### Step 5 — Install TLS certificates

```bash
# Copy ACM-issued certs to nginx cert volume
# (or use certbot with Route 53 DNS challenge)
sudo mkdir -p /opt/capsule/certs
sudo cp platform.crt /opt/capsule/certs/platform.crt
sudo cp platform.key /opt/capsule/certs/platform.key
sudo cp apps-wildcard.crt /opt/capsule/certs/apps-wildcard.crt
sudo cp apps-wildcard.key /opt/capsule/certs/apps-wildcard.key
```

### Step 6 — First deploy

```bash
# On control-plane EC2:
export AWS_REGION=us-east-1
export ECR_REGISTRY=123456789.dkr.ecr.us-east-1.amazonaws.com
export IMAGE_TAG=v1.0.0
bash /opt/capsule/deploy/scripts/deploy.sh control-plane v1.0.0

# On sandbox-host EC2:
bash /opt/capsule/deploy/scripts/deploy.sh sandbox-host v1.0.0
```

### Acceptance test

```bash
# Staging: one-command boot from scratch
docker compose \
  -f deploy/compose/docker-compose.control-plane.yml \
  -f deploy/compose/docker-compose.staging.yml \
  up -d

# Verify
curl http://localhost:8000/healthz   # should return {"status":"ok"}
```

---

## 3. Standard Deploy (Code Update)

Triggered automatically by CI on tag push (`v*.*.*`). For manual deploys:

```bash
# 1. Verify CI passed (green) for the commit/tag you are deploying

# 2. On control-plane EC2:
export IMAGE_TAG=v1.2.3
bash /opt/capsule/deploy/scripts/deploy.sh control-plane v1.2.3

# 3. On sandbox-host EC2:
bash /opt/capsule/deploy/scripts/deploy.sh sandbox-host v1.2.3

# 4. Verify health
curl https://platform.example.com/healthz
```

**Expected downtime:** < 5 seconds (Docker Compose recreates containers with `--remove-orphans`)

---

## 4. Platform Rollback

Use when a deploy causes regressions or the health check fails.

```bash
# Identify the last good image tag (check ECR or GitHub releases)
PREVIOUS_TAG=v1.2.2

# Roll back control-plane
ssh ubuntu@10.0.1.10 "
  export IMAGE_TAG=${PREVIOUS_TAG}
  export ECR_REGISTRY=123456789.dkr.ecr.us-east-1.amazonaws.com
  bash /opt/capsule/deploy/scripts/deploy.sh control-plane ${PREVIOUS_TAG}
"

# Roll back sandbox-host
ssh ubuntu@10.0.2.10 "
  export IMAGE_TAG=${PREVIOUS_TAG}
  export ECR_REGISTRY=123456789.dkr.ecr.us-east-1.amazonaws.com
  bash /opt/capsule/deploy/scripts/deploy.sh sandbox-host ${PREVIOUS_TAG}
"

# Verify
curl https://platform.example.com/healthz
```

> [!WARNING]
> Rolling back the platform does NOT automatically roll back individual capsule applications. Use the capsule rollback API (`POST /v1/capsules/{id}/rollback`) for application-level rollbacks. See CLI: `capsule rollback <id>`.

---

## 5. Restore from Backup

### 5a. Database (RDS Point-in-Time Restore)

Use when data corruption or accidental deletion occurs.

```bash
# 1. Identify the restore time (use CloudWatch logs to find the incident time)
RESTORE_TIME="2026-09-20T14:30:00Z"
SOURCE_INSTANCE="capsule-rds-prod"
NEW_INSTANCE="capsule-rds-prod-restored"

# 2. Initiate restore
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier ${SOURCE_INSTANCE} \
  --target-db-instance-identifier ${NEW_INSTANCE} \
  --restore-time ${RESTORE_TIME} \
  --db-subnet-group-name capsule-prod-subnet-group \
  --vpc-security-group-ids sg-xxxxxxxxx \
  --no-publicly-accessible \
  --region us-east-1

# 3. Wait for the new instance to become available (typically 15-30 minutes)
aws rds wait db-instance-available \
  --db-instance-identifier ${NEW_INSTANCE}

# 4. Get the new endpoint
NEW_ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier ${NEW_INSTANCE} \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text)

# 5. Update the DATABASE_URL secret to point to the new instance
# (use rotate-secrets.sh or update Secrets Manager manually)
aws secretsmanager put-secret-value \
  --region us-east-1 \
  --secret-id capsule/production/control-plane \
  --secret-string "$(aws secretsmanager get-secret-value \
    --secret-id capsule/production/control-plane \
    --query SecretString --output text \
    | python3 -c "import sys,json,os; d=json.load(sys.stdin); d['DATABASE_URL']=os.environ['NEW_ENDPOINT']; print(json.dumps(d))" \
    NEW_ENDPOINT="postgresql+asyncpg://capsule_user:PASS@${NEW_ENDPOINT}:5432/capsule_control")"

# 6. Restart control-plane to pick up new DATABASE_URL
ssh ubuntu@10.0.1.10 "sudo systemctl restart capsule-control-plane"

# 7. Verify
curl https://platform.example.com/healthz
```

### 5b. S3 Object Recovery (Capsule Bundle)

```bash
# List versions of an object (versioning is enabled on the bucket)
aws s3api list-object-versions \
  --bucket capsule-artifacts-prod \
  --prefix bundles/YOUR_APP_ID/

# Restore a specific version
aws s3api get-object \
  --bucket capsule-artifacts-prod \
  --key bundles/YOUR_APP_ID/v3.tar.gz \
  --version-id "YOUR_VERSION_ID" \
  /tmp/recovered-bundle.tar.gz
```

---

## 6. Key Rotation

### JWT Signing Key Rotation

```bash
# Rotate the JWT signing secret (generates a new key, updates Secrets Manager, restarts service)
export AWS_REGION=us-east-1
export AWS_SECRET_NAME=capsule/production/control-plane
export CONTROL_PLANE_HOST=10.0.1.10
export PLATFORM_DOMAIN=platform.example.com

# Dry run first
bash deploy/scripts/rotate-secrets.sh --dry-run

# Apply
bash deploy/scripts/rotate-secrets.sh
```

> [!CAUTION]
> After JWT rotation, existing user sessions will be invalidated and users must log in again. Plan rotation during low-traffic periods. All actively running capsules are unaffected (they use SDK auth, not user JWTs directly).

---

## 7. Kill Switch — Incident Response

The platform has a built-in kill switch to halt all active capsule containers in response to a security incident.

### Activate Kill Switch (all capsules)

```bash
# Via API (requires admin token)
curl -X POST https://platform.example.com/v1/admin/kill-switch \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "security-incident", "operator": "your-name"}'
```

### Activate Kill Switch (single capsule)

```bash
# Suspend a specific app
curl -X POST "https://platform.example.com/v1/capsules/${APP_ID}/suspend" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "security-incident"}'
```

### Emergency nginx 503 (no API access)

If the control plane is unreachable:

```bash
# SSH to edge VM and insert 503 maintenance page
ssh ubuntu@10.0.1.10
cat > /tmp/maintenance.conf << 'EOF'
server {
  listen 443 ssl http2 default_server;
  server_name _;
  ssl_certificate /etc/nginx/certs/platform.crt;
  ssl_certificate_key /etc/nginx/certs/platform.key;
  return 503 "Platform temporarily unavailable for maintenance.";
}
EOF
sudo docker exec capsule-control-plane-nginx-1 \
  sh -c 'cat > /etc/nginx/conf.d/maintenance.conf' < /tmp/maintenance.conf
sudo docker exec capsule-control-plane-nginx-1 nginx -s reload
```

To restore:
```bash
sudo docker exec capsule-control-plane-nginx-1 \
  rm /etc/nginx/conf.d/maintenance.conf
sudo docker exec capsule-control-plane-nginx-1 nginx -s reload
```

### Incident Response Checklist

1. **Detect** — Alert fires or report received
2. **Triage** — Severity 1 (data breach / RCE) or Severity 2 (service degradation)?
3. **Contain** — Activate kill switch if S1; suspend affected capsule if S2
4. **Communicate** — Notify affected org admins via platform notification system
5. **Investigate** — Pull audit logs: `GET /v1/admin/audit?start=<ISO>&end=<ISO>`
6. **Remediate** — Patch, rotate secrets, redeploy
7. **Post-mortem** — Write and publish within 5 business days

---

## 8. Monitoring & Alerting

### Health check endpoints

| Endpoint | Expected response |
|---|---|
| `GET /healthz` (control-plane) | `{"status": "ok", "version": "..."}` |
| `GET /healthz` (edge-proxy) | `{"status": "ok"}` |
| `GET /healthz` (egress-proxy) | `{"status": "ok"}` |
| `GET /healthz` (builder) | `{"status": "ok"}` |

### Grafana dashboards

Access Grafana at `http://monitoring-host:3000` (internal only):
- **Platform Overview** — error rate, request latency, sandbox launches, egress denials, active capsules
- **AI Gateway** — token usage/day, cost/day, budget headroom by org

### CloudWatch log groups

| Log Group | Content |
|---|---|
| `/capsule/control-plane` | FastAPI structured JSON logs |
| `/capsule/nginx` | nginx access + error logs |
| `/capsule/builder` | Build job logs |
| `/capsule/egress-proxy` | Allowed/denied egress events |

### Alert escalation

| Severity | Response time | Contact |
|---|---|---|
| Critical | 15 min | On-call via PagerDuty |
| Warning | 4 hours | ops@example.com |
| Security | Immediate | security@example.com + PagerDuty |

---

## 9. Backup Restore Drill Results

Run the drill before each production release and document results here.

### Drill procedure

```bash
export AWS_REGION=us-east-1
export RDS_INSTANCE_ID=capsule-rds-prod
export RDS_RESTORE_SUBNET_GROUP=capsule-prod-subnet-group
export RDS_RESTORE_SECURITY_GROUP=sg-xxxxxxxxx
export S3_BUCKET=capsule-artifacts-prod
export S3_TEST_OBJECT_KEY=bundles/test-app/v1.tar.gz
export AWS_SECRET_NAME=capsule/production/control-plane

bash deploy/scripts/backup-restore-drill.sh
```

### Drill log

| Date | Operator | RDS Result | S3 Result | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | — | — | — | Initial drill pending first production deploy |

> Document each drill run here. Expected output:
> ```
> [drill][PASS] RDS restore instance is available
> [drill][PASS] Schema verified: N public tables found in restored instance
> [drill][PASS] S3 bundle integrity verified (SHA-256 matches)
> ============================================
>  DRILL PASSED: RDS restore OK, S3 bundle OK
> ============================================
> ```

---

## 10. Human Task Checklist

These tasks cannot be automated and must be completed by a human operator before going live:

- [ ] **Public Suffix List (PSL) registration** — Submit `apps.example.com` to https://publicsuffix.org/submit/ so browsers treat each capsule subdomain as a separate registrable domain.
- [ ] **DNS setup** — Point `platform.example.com` A record and `*.apps.example.com` A record to the edge EC2 Elastic IP in your DNS provider.
- [ ] **ACM wildcard certificate** — Request `*.apps.example.com` and `platform.example.com` in AWS Certificate Manager. Validate via DNS challenge. Download/export certs if using nginx directly.
- [ ] **Legal pages** — Create `privacy policy` and `terms of service` pages and link them from the dashboard login screen.
- [ ] **Retention periods** — Set CloudWatch log group retention (suggested: 90 days) and RDS automated backup retention (suggested: 30 days) based on your compliance requirements.
- [ ] **AWS account separation** — Use separate AWS accounts (or at minimum separate VPCs + IAM boundaries) for staging and production. Never share the production RDS or S3 bucket with staging.
- [ ] **GitHub repository secrets** — Set in GitHub Settings → Secrets and Variables → Actions:
  - `AWS_STAGING_ROLE_ARN` (IAM role ARN for OIDC)
  - `AWS_PROD_ROLE_ARN`
  - `STAGING_CP_HOST`, `STAGING_SH_HOST`, `PROD_CP_HOST`, `PROD_SH_HOST`
  - `SSH_PRIVATE_KEY`, `SSH_PRIVATE_KEY_PROD`
  - `PAGERDUTY_ROUTING_KEY`
- [ ] **GitHub environment protection** — Add required reviewer(s) to the `production` GitHub environment.
- [ ] **First backup drill** — Run `backup-restore-drill.sh` and record results in section 9 above.
