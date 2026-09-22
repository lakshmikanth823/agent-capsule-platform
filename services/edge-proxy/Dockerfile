# ── Stage 1: build ───────────────────────────────────────────────────────────
FROM node:22-slim AS builder

WORKDIR /build

# Copy workspace root for npm workspace resolution
COPY package.json package-lock.json tsconfig.base.json ./
COPY packages/ packages/
COPY services/edge-proxy/package.json services/edge-proxy/
COPY services/edge-proxy/tsconfig.json services/edge-proxy/

RUN npm ci --workspace=services/edge-proxy --include-workspace-root

RUN npm run build --workspace=@capsule/manifest-schema \
 && npm run build --workspace=@capsule/sdk \
 && npm run build --workspace=@capsule/sandbox-driver

COPY services/edge-proxy/src/ services/edge-proxy/src/

RUN npm run build --workspace=services/edge-proxy

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM node:22-slim AS runtime

RUN groupadd --gid 1001 capsule \
    && useradd --uid 1001 --gid 1001 --no-create-home capsule \
    && apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /build/node_modules ./node_modules
COPY --from=builder /build/packages ./packages
COPY --from=builder /build/services/edge-proxy/dist ./services/edge-proxy/dist
COPY --from=builder /build/services/edge-proxy/package.json ./services/edge-proxy/package.json

WORKDIR /app/services/edge-proxy

USER capsule

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

CMD ["node", "dist/index.js"]
