# ── Stage 1: dependency builder ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps into an isolated venv so we can copy only the venv
COPY services/control-plane/requirements.txt ./requirements.txt
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip "setuptools>=78.1.1" \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /opt/venv/lib/python3.12/site-packages/setuptools*

# ── Stage 2: runtime image ───────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Security: non-root user
RUN groupadd --gid 1001 capsule \
    && useradd --uid 1001 --gid 1001 --no-create-home capsule

# Runtime libs only (libpq for asyncpg)
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    libpq5 curl awscli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
COPY services/control-plane/alembic/ ./alembic/
COPY services/control-plane/alembic.ini ./
COPY services/control-plane/src/ ./src/

# Copy entrypoint (injected by deploy pipeline)
COPY deploy/scripts/entrypoint-control-plane.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER capsule

EXPOSE 8000

# Healthcheck: lightweight ping
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/entrypoint.sh"]
