# ── Stage 1: build ───────────────────────────────────────────────────────────
FROM node:22-slim AS builder

WORKDIR /build

COPY package.json package-lock.json ./
COPY services/builder/package.json services/builder/
COPY services/builder/tsconfig.json services/builder/
COPY tsconfig.base.json ./

RUN npm ci --workspace=services/builder --include-workspace-root

COPY services/builder/src/ services/builder/src/

RUN npm run build --workspace=services/builder

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM node:22-slim AS runtime

# Builder service needs docker CLI to launch sandboxed build containers
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl docker.io \
    && rm -rf /var/lib/apt/lists/*

# Non-root user but member of docker group so it can reach the Docker socket
RUN groupadd --gid 1001 capsule \
    && useradd --uid 1001 --gid 1001 --no-create-home --groups docker capsule

WORKDIR /app

COPY --from=builder /build/services/builder/dist ./dist
COPY --from=builder /build/services/builder/package.json ./

RUN npm install --omit=dev --ignore-scripts

USER capsule

EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8090/healthz || exit 1

CMD ["node", "dist/index.js"]
