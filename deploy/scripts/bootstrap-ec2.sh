#!/bin/bash
# ==============================================================================
# bootstrap-ec2.sh
# One-time setup for a Capsule Platform EC2 instance (Ubuntu 24.04 LTS).
# Installs: Docker CE, Docker Compose plugin, AWS CLI v2, gVisor (runsc).
# Registers gVisor as a Docker runtime.
# Hardens SSH and firewall.
# Installs and enables the appropriate capsule systemd service.
#
# Usage:
#   sudo bash bootstrap-ec2.sh [control-plane|sandbox-host]
#
# Environment variables (optional, override defaults):
#   CAPSULE_DEPLOY_DIR — defaults to /opt/capsule
#   RUNSC_VERSION      — gVisor release to install (defaults to latest stable)
# ==============================================================================

set -euo pipefail

ROLE="${1:-control-plane}"
DEPLOY_DIR="${CAPSULE_DEPLOY_DIR:-/opt/capsule}"
RUNSC_VERSION="${RUNSC_VERSION:-latest}"

log() { echo "[bootstrap][$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: must run as root" >&2
    exit 1
fi

if [[ "${ROLE}" != "control-plane" && "${ROLE}" != "sandbox-host" ]]; then
    echo "ERROR: ROLE must be 'control-plane' or 'sandbox-host'" >&2
    exit 1
fi

log "Bootstrapping EC2 as role: ${ROLE}"

# ── 1. System update ──────────────────────────────────────────────────────────
log "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg lsb-release jq unzip \
    ufw fail2ban

# ── 2. Docker CE ─────────────────────────────────────────────────────────────
log "Installing Docker CE..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -qq
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker
log "Docker CE installed: $(docker --version)"

# ── 3. AWS CLI v2 ─────────────────────────────────────────────────────────────
log "Installing AWS CLI v2..."
ARCH=$(dpkg --print-architecture)
if [ "${ARCH}" = "amd64" ]; then AWS_ARCH="x86_64"; else AWS_ARCH="aarch64"; fi
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp/
/tmp/aws/install --update
rm -rf /tmp/awscliv2.zip /tmp/aws
log "AWS CLI installed: $(aws --version)"

# ── 4. gVisor (runsc) — sandbox host only ────────────────────────────────────
if [ "${ROLE}" = "sandbox-host" ]; then
    log "Installing gVisor (runsc)..."

    GVISOR_URL="https://storage.googleapis.com/gvisor/releases/release/latest/$(uname -m)"

    curl -fsSL "${GVISOR_URL}/runsc" -o /usr/local/bin/runsc
    curl -fsSL "${GVISOR_URL}/runsc.sha512" -o /tmp/runsc.sha512

    # Verify integrity
    (cd /usr/local/bin && sha512sum -c /tmp/runsc.sha512)
    chmod +x /usr/local/bin/runsc
    rm /tmp/runsc.sha512

    log "gVisor installed: $(runsc --version)"

    # Register runsc as a Docker runtime
    cat > /etc/docker/daemon.json <<'DAEMON_JSON'
{
  "runtimes": {
    "runsc": {
      "path": "/usr/local/bin/runsc",
      "runtimeArgs": [
        "--platform=systrap",
        "--network=sandbox"
      ]
    }
  },
  "log-driver": "awslogs",
  "log-opts": {
    "awslogs-region": "us-east-1"
  },
  "default-ulimits": {
    "nofile": {
      "Hard": 65536,
      "Name": "nofile",
      "Soft": 65536
    }
  }
}
DAEMON_JSON

    systemctl restart docker
    # Verify gVisor is registered
    docker info --format '{{json .Runtimes}}' | grep -q runsc \
        && log "gVisor runtime registered with Docker" \
        || { log "ERROR: gVisor not registered"; exit 1; }
else
    # Control plane: standard Docker daemon config (with CloudWatch logging)
    cat > /etc/docker/daemon.json <<'DAEMON_JSON'
{
  "log-driver": "awslogs",
  "log-opts": {
    "awslogs-region": "us-east-1"
  },
  "default-ulimits": {
    "nofile": {
      "Hard": 65536,
      "Name": "nofile",
      "Soft": 65536
    }
  }
}
DAEMON_JSON
    systemctl restart docker
fi

# ── 5. Firewall (UFW) ─────────────────────────────────────────────────────────
log "Configuring firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh    # port 22 (restrict to bastion IP in production)

if [ "${ROLE}" = "control-plane" ]; then
    ufw allow 80/tcp
    ufw allow 443/tcp
fi

if [ "${ROLE}" = "sandbox-host" ]; then
    # Egress proxy port — allow only from VPC CIDR (set the real CIDR below)
    ufw allow from 10.0.0.0/8 to any port 3128
    ufw allow from 172.16.0.0/12 to any port 3128
    # Sandbox runner port — allow only from control-plane VPC CIDR
    ufw allow from 10.0.0.0/8 to any port 8095
    ufw allow from 172.16.0.0/12 to any port 8095
fi

ufw --force enable
log "UFW configured"

# ── 6. Harden SSH ─────────────────────────────────────────────────────────────
log "Hardening SSH..."
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?X11Forwarding.*/X11Forwarding no/' /etc/ssh/sshd_config
systemctl restart ssh
log "SSH hardened"

# ── 7. Deploy directory ───────────────────────────────────────────────────────
log "Creating deploy directory: ${DEPLOY_DIR}"
mkdir -p "${DEPLOY_DIR}"
# env.conf is populated by the CI/CD pipeline — not by this script
touch "${DEPLOY_DIR}/env.conf"
chmod 640 "${DEPLOY_DIR}/env.conf"

# Copy systemd unit
if [ "${ROLE}" = "control-plane" ]; then
    cp "${DEPLOY_DIR}/deploy/systemd/capsule-control-plane.service" \
        /etc/systemd/system/capsule-control-plane.service
    systemctl daemon-reload
    systemctl enable capsule-control-plane
    log "capsule-control-plane.service enabled"
else
    cp "${DEPLOY_DIR}/deploy/systemd/capsule-sandbox-host.service" \
        /etc/systemd/system/capsule-sandbox-host.service
    systemctl daemon-reload
    systemctl enable capsule-sandbox-host
    log "capsule-sandbox-host.service enabled"
fi

log "Bootstrap complete. Reboot recommended before first start."
log "After reboot: systemctl start capsule-${ROLE}"
