# ── Stage 1: build ───────────────────────────────────────────────────────────
FROM node:22-slim AS builder

WORKDIR /build

COPY package.json package-lock.json tsconfig.base.json ./
COPY packages/ packages/
COPY services/sandbox-runner/package.json services/sandbox-runner/
COPY services/sandbox-runner/tsconfig.json services/sandbox-runner/

RUN npm ci

RUN npm run build --workspace=@capsule/manifest-schema \
 && npm run build --workspace=@capsule/sdk \
 && npm run build --workspace=@capsule/sandbox-driver

COPY services/sandbox-runner/src/ services/sandbox-runner/src/

RUN npm run build --workspace=@capsule/sandbox-runner

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM node:22-slim AS runtime

# Sandbox runner needs docker CLI to manage gVisor/runsc containers on sandbox host
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    curl docker.io awscli \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/node_modules/npm

# Non-root user but member of docker group so it can reach the Docker socket
RUN groupadd --gid 1001 capsule \
    && useradd --uid 1001 --gid 1001 --no-create-home --groups docker capsule

WORKDIR /app

COPY --from=builder /build/node_modules ./node_modules
COPY --from=builder /build/packages ./packages
COPY --from=builder /build/services/sandbox-runner/dist ./services/sandbox-runner/dist
COPY --from=builder /build/services/sandbox-runner/package.json ./services/sandbox-runner/package.json

COPY deploy/scripts/entrypoint-node.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app/services/sandbox-runner

USER capsule

EXPOSE 8095

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8095/healthz || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["node", "dist/index.js"]
