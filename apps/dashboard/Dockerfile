# ── Stage 1: Vite build ───────────────────────────────────────────────────────
FROM node:22-slim AS builder

WORKDIR /build

COPY package.json package-lock.json ./
COPY apps/dashboard/package.json apps/dashboard/
COPY apps/dashboard/tsconfig*.json apps/dashboard/
COPY apps/dashboard/vite.config* apps/dashboard/ 2>/dev/null || true
COPY tsconfig.base.json ./

# Also copy SDK (dashboard imports it)
COPY packages/ packages/

RUN npm ci --workspace=apps/dashboard --include-workspace-root

COPY apps/dashboard/src/ apps/dashboard/src/
COPY apps/dashboard/index.html apps/dashboard/ 2>/dev/null || true
COPY apps/dashboard/public/ apps/dashboard/public/ 2>/dev/null || true

RUN npm run build --workspace=apps/dashboard

# ── Stage 2: nginx static server ─────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

COPY deploy/nginx/dashboard.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /build/apps/dashboard/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost/index.html || exit 1

CMD ["nginx", "-g", "daemon off;"]
