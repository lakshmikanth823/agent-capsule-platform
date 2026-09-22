# ── Stage 1: build ───────────────────────────────────────────────────────────
FROM node:22-slim AS builder

WORKDIR /build

COPY package.json package-lock.json ./
COPY services/egress-proxy/package.json services/egress-proxy/
COPY services/egress-proxy/tsconfig.json services/egress-proxy/
COPY tsconfig.base.json ./

RUN npm ci --workspace=services/egress-proxy --include-workspace-root

COPY services/egress-proxy/src/ services/egress-proxy/src/

RUN npm run build --workspace=services/egress-proxy

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM node:22-slim AS runtime

RUN groupadd --gid 1001 capsule \
    && useradd --uid 1001 --gid 1001 --no-create-home capsule \
    && apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/node_modules/npm

WORKDIR /app

COPY --from=builder /build/services/egress-proxy/dist ./dist
COPY --from=builder /build/services/egress-proxy/package.json ./

USER capsule

EXPOSE 3128

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:3128/healthz || exit 1

CMD ["node", "dist/index.js"]
