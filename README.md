# Software Capsule Platform

The Software Capsule Platform enables external AI agents to securely build, publish, share, and operate small, purpose-built applications without requiring users to manage cloud infrastructure.

---

## Architecture Overview

- **Control Plane (`services/control-plane`)**: Authoritative REST API (Python/FastAPI), Capsule registry, version lifecycle, and PostgreSQL metadata.
- **Edge Proxy (`services/edge-proxy`)**: Reverse proxy with per-Capsule origin isolation (`http://<capsule-id>.localhost:8080`), OIDC authentication, and JWT injection.
- **Isolated Builder (`services/builder`)**: Ephemeral containerized builder that compiles Node.js 22 TypeScript applications into versioned artifacts.
- **Manifest Schema (`packages/manifest-schema`)**: Shared JSON Schema validator and TypeScript types for `capsule.manifest.yaml`.
- **Sandbox Driver (`packages/sandbox-driver`)**: Pluggable sandbox abstraction (`DockerSandboxDriver` for Phase 0 WSL2 Docker).
- **Runtime SDK (`packages/sdk`)**: `@capsule/sdk` for blessed Node.js 22 applications (HTTP, SQLite, identity).
- **CLI (`packages/cli`)**: `capsule` CLI for publishing, sharing, validating, and local emulation.

---

## Prerequisites

- **Node.js**: `v22.0.0` or higher (Node `v24` supported)
- **npm**: `v10.0.0` or higher
- **Python**: `3.12+` with `pip`
- **Docker Desktop**: Running with WSL2 backend enabled
- **Git**: `2.40+`

---

## Getting Started

### 1. Install Dependencies
```bash
npm install
```

### 2. Configure Environment
```bash
cp .env.example .env
```

### 3. Start Local Development Infrastructure
Start PostgreSQL and MinIO:
```bash
docker compose up -d
```

### 4. Run Tests
Run the entire test suite across all TypeScript packages and the Python control plane:
```bash
npm test
```

To run TypeScript or Python tests individually:
```bash
npm run test:ts
npm run test:py
```

---

## Documentation

- [`docs/TRD.md`](docs/TRD.md) — Technical Requirements Document (Source of Truth #1)
- [`docs/PRD.md`](docs/PRD.md) — Product Requirements Document
- [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) — Phase 0 Step-by-Step Build Plan
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — Architectural Decisions Log
- [`docs/REPO_LAYOUT.md`](docs/REPO_LAYOUT.md) — Monorepo Layout Specification
- [`docs/CONFLICTS_AND_GAPS.md`](docs/CONFLICTS_AND_GAPS.md) — Catalog of Document Resolving
