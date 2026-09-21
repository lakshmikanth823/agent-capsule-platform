# Monorepo Layout: Software Capsule Platform

**Status:** Proposed Architecture  
**Date:** 2026-09-21  
**Aligned With:** `docs/TRD.md` (Sections 3, 42, 51, 57), `docs/PRD.md`, `docs/api-cli-spec/`, `docs/manifest-spec/`

This document defines the monorepo directory layout for the Software Capsule Platform, organizing the control plane, data plane, edge, CLI, SDK, and shared libraries into modular, independently testable workspaces.

---

## 1. Directory Tree Overview

```text
capsule-platform/
├── .agents/                        # Agent workflows and project rules
│   └── rules/
│       ├── project-rules.md        # Source of truth, invariants, workflow
│       └── reviews.md              # Review protocols between prompts/phases
│
├── docs/                           # Architecture, specs, plans, decisions
│   ├── PRD.md
│   ├── TRD.md
│   ├── FRONTEND_DESIGN.md
│   ├── BUILD_PLAN.md               # Phase 0 step-by-step tasks
│   ├── CONFLICTS_AND_GAPS.md       # Open decisions catalog
│   ├── REPO_LAYOUT.md              # This document
│   ├── DECISIONS.md                # Resolved architectural decisions
│   ├── api-cli-spec/
│   ├── backend-database-schema/
│   └── manifest-spec/
│
├── services/                       # Standalone backend microservices / daemons
│   ├── control-plane/              # Control Plane REST API & Orchestration (FastAPI)
│   ├── edge-proxy/                 # Edge Proxy, TLS, Origin & Identity Routing
│   └── builder/                    # Isolated Artifact Build Service
│
├── packages/                       # Shared libraries and developer tooling
│   ├── manifest-schema/            # Manifest JSON Schema & validation engine
│   ├── sandbox-driver/             # SandboxDriver abstraction & Docker driver
│   ├── sdk/                        # Blessed Node 22 TypeScript SDK (@capsule/sdk)
│   └── cli/                        # capsule developer & agent CLI tool
│
├── apps/                           # Web applications
│   └── dashboard/                  # Platform management UI (React/Vite)
│
├── examples/                       # Blessed reference applications
│   └── leave-tracker/              # Canonical Node 22 + TypeScript reference Capsule
│
├── tests/                          # Cross-service and end-to-end tests
│   └── e2e/                        # Full loop acceptance tests (<60s publish & open)
│
├── docker-compose.yml              # Local developer stack (PostgreSQL, MinIO, Edge, API)
├── .env.example                    # Environment template with zero hardcoded secrets
├── pnpm-workspace.yaml             # Node.js workspace definitions
├── package.json                    # Root workspace script definitions
├── pyproject.toml                  # Python environment definitions (FastAPI services)
├── tsconfig.base.json              # Shared TypeScript compiler configuration
└── README.md                       # Platform overview & quickstart
```

---

## 2. Component Details & Responsibilities

### 2.1 `services/control-plane/`
- **Tech Stack:** Python 3.12+ / FastAPI / SQLAlchemy / asyncpg / Pydantic v2
- **Responsibilities:**
  - Control-plane REST API (`/v1/capsules`, `/v1/capsules/{id}/publish`, `/v1/capsules/{id}/shares`, etc.)
  - Authoritative validation, capability checks, and policy evaluation
  - Capsule registry and version lifecycle state machine
  - Database migrations for PostgreSQL control metadata (`alembic/`)
  - Storage integration for version artifacts and SQLite snapshots
  - Security audit logging (`audit_events`)
- **Structure:**
  ```text
  services/control-plane/
  ├── alembic/                      # Database migration scripts
  ├── src/
  │   ├── api/                      # Route handlers (/v1/capsules, /v1/shares, etc.)
  │   ├── core/                     # Configuration, security, audit logging
  │   ├── db/                       # SQLAlchemy models & database sessions
  │   ├── services/                 # Business logic: publish, rollback, policy
  │   ├── storage/                  # Local and S3 object storage drivers
  │   └── main.py                   # FastAPI application entry point
  ├── tests/                        # Unit & integration tests
  ├── pyproject.toml
  └── Dockerfile
  ```

---

### 2.2 `services/edge-proxy/`
- **Tech Stack:** Node.js 22 / TypeScript / Fastify or HTTP reverse proxy
- **Responsibilities:**
  - Front door for browser users requesting Capsule applications
  - Per-Capsule origin isolation (`http://<capsule-id>.localhost:8080`)
  - OIDC / session cookie authentication verification
  - Share grant authorization checking
  - Signed identity context JWT injection (`X-Capsule-Identity`) into upstream requests
  - Framing and security header enforcement (`X-Frame-Options: DENY`, strict CSP)
  - Scale-to-zero wake-on-request trigger
- **Structure:**
  ```text
  services/edge-proxy/
  ├── src/
  │   ├── auth/                     # OIDC token validation & session cookies
  │   ├── router/                   # Subdomain routing to active sandbox ports
  │   ├── security/                 # Origin validation, CSP, and framing headers
  │   ├── token/                    # Signed platform identity context generator
  │   └── index.ts                  # Edge server entry point
  ├── tests/
  ├── package.json
  └── Dockerfile
  ```

---

### 2.3 `services/builder/`
- **Tech Stack:** Dockerized isolated build runner (Node 22 / npm)
- **Responsibilities:**
  - Builds untrusted source code in a constrained, ephemeral container
  - Enforces dependency lockfiles (`package-lock.json`)
  - No access to platform databases or production secrets
  - Produces immutable `.tar.gz` versioned artifacts
- **Structure:**
  ```text
  services/builder/
  ├── src/
  │   └── build.ts                  # Build orchestrator script
  ├── Dockerfile.builder            # Hardened build environment image
  ├── tests/
  └── package.json
  ```

---

### 2.4 `packages/manifest-schema/`
- **Tech Stack:** TypeScript / JSON Schema Draft 2020-12
- **Responsibilities:**
  - Publishes `capsule.manifest.schema.json`
  - Provides TypeScript types and validation functions
  - Shared across CLI, Control Plane, and Builder
- **Structure:**
  ```text
  packages/manifest-schema/
  ├── schema/
  │   └── capsule.manifest.schema.json
  ├── src/
  │   ├── index.ts
  │   ├── types.ts                  # Generated or typed manifest interfaces
  │   └── validator.ts              # Schema + semantic validation logic
  ├── tests/
  └── package.json
  ```

---

### 2.5 `packages/sandbox-driver/`
- **Tech Stack:** TypeScript (or Python adapter)
- **Responsibilities:**
  - Defines the `SandboxDriver` interface (Project Rule 9)
  - `DockerSandboxDriver`: Phase 0 container driver using Docker Desktop (WSL2 backend)
  - `DevMockSandboxDriver`: Development mock driver (explicitly NOT a security boundary)
  - Prepares extension points for `FirecrackerSandboxDriver` and `GVisorSandboxDriver`
- **Structure:**
  ```text
  packages/sandbox-driver/
  ├── src/
  │   ├── interface.ts              # SandboxDriver abstract contract
  │   ├── docker.ts                 # Docker container driver (WSL2)
  │   └── mock.ts                   # Mock dev driver (NOT a security boundary)
  ├── tests/
  └── package.json
  ```

---

### 2.6 `packages/sdk/`
- **Tech Stack:** Node.js 22 / TypeScript
- **Package Name:** `@capsule/sdk`
- **Responsibilities:**
  - Standard runtime SDK for the blessed application shape
  - Provides HTTP request routing, SQLite database access, and verified identity parsing
  - Does NOT act as the security boundary (platform enforces security externally)
- **Structure:**
  ```text
  packages/sdk/
  ├── src/
  │   ├── db.ts                     # SQLite wrapper (better-sqlite3 / node:sqlite)
  │   ├── identity.ts               # Parses & validates X-Capsule-Identity JWT
  │   ├── server.ts                 # Minimal HTTP server abstraction
  │   └── index.ts                  # Main SDK exports
  ├── tests/
  └── package.json
  ```

---

### 2.7 `packages/cli/`
- **Tech Stack:** TypeScript / Node.js 22 / `commander`
- **Binary Name:** `capsule`
- **Responsibilities:**
  - Agent and human developer CLI
  - Commands: `init`, `validate`, `publish`, `share`, `status`, `dev`
  - Machine-readable JSON output for automated agent loops (`--json`)
- **Structure:**
  ```text
  packages/cli/
  ├── bin/
  │   └── capsule.js                # CLI executable entry point
  ├── src/
  │   ├── commands/                 # Command implementations (init, publish, etc.)
  │   ├── emulator/                 # Local dev emulator for `capsule dev`
  │   ├── client/                   # Control-plane API HTTP client
  │   └── index.ts
  ├── tests/
  └── package.json
  ```

---

### 2.8 `apps/dashboard/`
- **Tech Stack:** React / TypeScript / Vite / Tailwind CSS
- **Responsibilities:**
  - Human web dashboard for inspecting Capsules, managing sharing, and previewing permissions
  - Deferred in Phase 0; populated in Phase 1 & 2 per wireframes in `docs/Frontend_Wireframes.*`
- **Structure:**
  ```text
  apps/dashboard/
  ├── src/
  │   ├── components/               # UI components
  │   ├── pages/                    # Dashboard, ShareModal, PermissionPreview
  │   └── App.tsx
  ├── package.json
  └── vite.config.ts
  ```

---

### 2.9 `examples/leave-tracker/`
- **Tech Stack:** Node.js 22 / TypeScript / `@capsule/sdk`
- **Responsibilities:**
  - Canonical reference application matching TRD Section 6 & PRD
  - Declares `capsule.manifest.yaml`
  - Demonstrates SQLite persistence, identity inspection, and role-based UI
- **Structure:**
  ```text
  examples/leave-tracker/
  ├── capsule.manifest.yaml         # Manifest contract
  ├── src/
  │   └── index.ts                  # Blessed application code
  ├── package.json
  └── tsconfig.json
  ```

---

### 2.10 `tests/e2e/`
- **Responsibilities:**
  - Automated end-to-end integration tests verifying Phase 0 exit criterion
  - `phase0_loop.test.ts`: Automates `capsule init` $\rightarrow$ `validate` $\rightarrow$ `publish` $\rightarrow$ `share` $\rightarrow$ colleague HTTP fetch in $<60$ seconds.
