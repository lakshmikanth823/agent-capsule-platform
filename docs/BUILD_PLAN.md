# Phase 0 Build Plan: "Prove the Loop"

**Goal:** An agent publishes a small app with the CLI and a colleague opens it, in under 60 seconds.  
**Scope:** Phase 0 (Alpha) deliverables only. No capability escalation, egress proxy, or enterprise SSO from later phases.

---

## Task Dependency Graph

```text
Task 0.1 (Monorepo & Tooling)
  ├── Task 0.2 (Manifest Schema & Validation)
  │     └── Task 0.6 (Reference App & SDK)
  │     └── Task 0.8 (Control Plane API)
  │     └── Task 0.10 (CLI)
  ├── Task 0.3 (DB Models & Migrations)
  │     └── Task 0.8 (Control Plane API)
  ├── Task 0.4 (Object Storage Driver)
  │     └── Task 0.7 (Isolated Build Service)
  │     └── Task 0.8 (Control Plane API)
  ├── Task 0.5 (Sandbox Driver Interface & Docker Driver)
  │     └── Task 0.9 (Edge Proxy & Origin Routing)
  │     └── Task 0.8 (Control Plane API - deployment execution)
  └── Task 0.7 (Isolated Build Service)
        └── Task 0.8 (Control Plane API)
              ├── Task 0.9 (Edge Proxy & Auth Integration)
              ├── Task 0.10 (CLI)
              └── Task 0.11 (Local Dev Emulator: capsule dev)
                    └── Task 0.12 (End-to-End Loop Test < 60s)
```

---

## Detailed Task Breakdown

### Task 0.1: Monorepo Foundation & Tooling Setup

- **Goal:** Initialize monorepo workspace configuration, linting, formatting, type checking, and Docker Compose development environment.
- **Files / Modules Touched:**
  - `package.json`, `pnpm-workspace.yaml` (or npm/yarn workspaces)
  - `pyproject.toml` (for Python control-plane services)
  - `docker-compose.dev.yml` (PostgreSQL, local storage/MinIO)
  - `.env.example`, `.gitignore`, `tsconfig.base.json`
- **Dependencies:** None.
- **Acceptance Criteria:**
  - `pnpm install` (or npm) succeeds across all packages.
  - Python environment setup works with `uv` or `poetry`/`venv`.
  - `docker compose -f docker-compose.dev.yml up -d` brings up clean PostgreSQL 16 instance.
  - Lint and typecheck commands pass cleanly across all modules.

---

### Task 0.2: Shared Manifest Schema & Validation Library

- **Goal:** Implement the manifest validation library conforming to `docs/manifest-spec/` (`capsule.manifest.schema.json`) with strict syntax, schema, and semantic checks.
- **Files / Modules Touched:**
  - `packages/manifest-schema/src/index.ts`
  - `packages/manifest-schema/src/validator.ts`
  - `packages/manifest-schema/src/types.ts`
  - `packages/manifest-schema/tests/validator.test.ts`
- **Dependencies:** Task 0.1.
- **Acceptance Criteria:**
  - Validates `capsule.manifest.yaml` against JSON Schema draft 2020-12.
  - Semantic checks enforce: `shape == 'web-app'`, `runtime == 'node22'`, valid naming regex (`^[a-z0-9][a-z0-9-]{0,62}$`), and memory/CPU limits.
  - Rejects unknown top-level properties (`additionalProperties: false`).
  - Unit tests achieve 100% coverage across valid and invalid sample manifests.

---

### Task 0.3: Control Plane Database Models & Migrations

- **Goal:** Set up PostgreSQL database models and migrations for the control plane based on `docs/backend-database-schema/`.
- **Files / Modules Touched:**
  - `services/control-plane/src/db/models.py` (or TypeScript Prisma/Drizzle models)
  - `services/control-plane/src/db/session.py`
  - `services/control-plane/alembic/` (or migration scripts matching `backend_schema.sql`)
  - `services/control-plane/tests/test_db_models.py`
- **Dependencies:** Task 0.1.
- **Acceptance Criteria:**
  - Schema migrations create tables: `organizations`, `users`, `organization_members`, `apps`, `app_versions`, `app_shares`, `app_share_policies`, `audit_events`.
  - Foreign keys, unique constraints (e.g. `(identity_issuer, identity_subject)` and `(org_id, app_key)`), and indexes are created.
  - Unit test verifies inserting, querying, and relational integrity of core models.

---

### Task 0.4: Storage & Object Store Driver

- **Goal:** Implement an abstract `StorageDriver` with a `LocalStorageDriver` (for local dev) and `S3StorageDriver` (for S3/MinIO) for storing version artifacts, SQLite snapshots, and file uploads.
- **Files / Modules Touched:**
  - `services/control-plane/src/storage/driver.py`
  - `services/control-plane/src/storage/local.py`
  - `services/control-plane/src/storage/s3.py`
  - `services/control-plane/tests/test_storage.py`
- **Dependencies:** Task 0.1.
- **Acceptance Criteria:**
  - Path layout matches TRD Section 12: `capsules/{capsule_id}/artifacts/{version_id}.tar.gz` and `snapshots/{snapshot_id}.sqlite`.
  - Can write, stream read, delete, and check existence of objects.
  - Raw storage credentials are never returned or leaked to callers.

---

### Task 0.5: Sandbox Driver Interface & Docker Sandbox Driver

- **Goal:** Define the `SandboxDriver` interface (Project Rule 9) and implement a `DockerSandboxDriver` using Docker Desktop (WSL2 backend) for isolating untrusted Capsule execution.
- **Files / Modules Touched:**
  - `packages/sandbox-driver/src/interface.ts` (or Python equivalent in control plane)
  - `packages/sandbox-driver/src/docker-driver.ts`
  - `packages/sandbox-driver/src/dev-mock-driver.ts` (explicitly documented as NOT a security boundary)
  - `packages/sandbox-driver/tests/docker-driver.test.ts`
- **Dependencies:** Task 0.1.
- **Acceptance Criteria:**
  - Implements methods: `createSandbox(spec)`, `start(id)`, `stop(id)`, `inspect(id)`, `destroy(id)`.
  - `DockerSandboxDriver` enforces: non-root user, CPU limit (`limits.cpu`), memory limit (`limits.memory_mb`), read-only rootfs where appropriate, controlled volume mount for SQLite directory, and isolated bridge network.
  - Explicitly documents `dev-mock-driver.ts` as NOT a security boundary.
  - Integration test starts a test container, verifies resource constraints, health checks the container, and cleanly stops it.

---

### Task 0.6: Reference Application & Platform SDK (`@capsule/sdk`)

- **Goal:** Create the blessed Node.js 22 + TypeScript reference application and minimal platform SDK.
- **Files / Modules Touched:**
  - `packages/sdk/package.json`
  - `packages/sdk/src/index.ts`
  - `packages/sdk/src/server.ts`
  - `packages/sdk/src/db.ts`
  - `packages/sdk/src/identity.ts`
  - `examples/leave-tracker/package.json`
  - `examples/leave-tracker/capsule.manifest.yaml`
  - `examples/leave-tracker/src/index.ts`
- **Dependencies:** Task 0.2.
- **Acceptance Criteria:**
  - SDK provides `createApp`, `getDb()` (wrapper for SQLite), and `getIdentity(req)` for reading verified identity context.
  - Reference app implements a simple working leave-tracker web app with HTML/JSON endpoints.
  - Reference app bundle size without `node_modules` is under 5 MB.
  - App starts cleanly on Node.js 22.

---

### Task 0.7: Isolated Build Service

- **Goal:** Implement the isolated builder that receives an app directory or source tarball, runs dependency installation and build in a restricted container, and outputs a versioned artifact.
- **Files / Modules Touched:**
  - `services/builder/Dockerfile`
  - `services/builder/src/build.py` (or TypeScript)
  - `services/builder/tests/test_build.py`
- **Dependencies:** Task 0.1, Task 0.4.
- **Acceptance Criteria:**
  - Builder runs inside a temporary container without host secrets or control-plane DB access.
  - Builds the Node 22 + TypeScript app (`npm ci --ignore-scripts`, `npm run build` if present).
  - Emits `.tar.gz` artifact stored via Task 0.4 `StorageDriver`.
  - Enforces timeout (e.g. 60s) and memory limits during build.

---

### Task 0.8: Control Plane API

- **Goal:** Implement the authoritative REST API for creating apps, validating manifests, publishing versions, managing sharing, and querying status/logs.
- **Files / Modules Touched:**
  - `services/control-plane/src/main.py`
  - `services/control-plane/src/api/v1/capsules.py` (or `apps.py`)
  - `services/control-plane/src/api/v1/versions.py`
  - `services/control-plane/src/api/v1/shares.py`
  - `services/control-plane/src/services/publish_service.py`
  - `services/control-plane/src/middleware/errors.py`
  - `services/control-plane/tests/test_api.py`
- **Dependencies:** Tasks 0.2, 0.3, 0.4, 0.5, 0.7.
- **Acceptance Criteria:**
  - Implements endpoints: `POST /v1/capsules`, `POST /v1/capsules/{id}/validate`, `POST /v1/capsules/{id}/publish` (with `Idempotency-Key`), `GET /v1/capsules/{id}/versions`, `POST /v1/capsules/{id}/shares`, `GET /v1/capsules/{id}/shares`.
  - Structured errors conform strictly to `docs/api-cli-spec/API_CLI_SPEC.md` and TRD Section 45.
  - Every privileged mutation writes an audit event to `audit_events`.
  - Publish orchestrates: Validate $\rightarrow$ Build $\rightarrow$ Snapshot DB $\rightarrow$ Deploy Sandbox $\rightarrow$ Health Check $\rightarrow$ Activate Version.

---

### Task 0.9: Edge Proxy & Origin Routing

- **Goal:** Implement the reverse proxy providing per-Capsule origin isolation, authentication (OIDC/session verification), and request forwarding to the active sandbox container.
- **Files / Modules Touched:**
  - `services/edge-proxy/src/index.ts` (or Go/Python proxy)
  - `services/edge-proxy/src/auth.ts`
  - `services/edge-proxy/src/router.ts`
  - `services/edge-proxy/src/token.ts`
  - `services/edge-proxy/tests/proxy.test.ts`
- **Dependencies:** Task 0.5, Task 0.8.
- **Acceptance Criteria:**
  - Routes `http://<capsule-id>.localhost:8080` to the corresponding sandbox container port.
  - Verifies user authentication and share authorization before proxying.
  - Injects signed platform identity JWT into request header `X-Capsule-Identity` (per TRD Section 15).
  - Enforces origin isolation: cookies are scoped strictly to the application origin; framing restrictions (`X-Frame-Options: DENY`, strict CSP) are attached.

---

### Task 0.10: CLI (`capsule`)

- **Goal:** Build the developer and agent CLI implementing authentication, manifest initialization, validation, publishing, and sharing.
- **Files / Modules Touched:**
  - `packages/cli/package.json`
  - `packages/cli/src/index.ts`
  - `packages/cli/src/commands/init.ts`
  - `packages/cli/src/commands/validate.ts`
  - `packages/cli/src/commands/publish.ts`
  - `packages/cli/src/commands/share.ts`
  - `packages/cli/src/commands/status.ts`
  - `packages/cli/tests/cli.test.ts`
- **Dependencies:** Task 0.2, Task 0.8.
- **Acceptance Criteria:**
  - `capsule init` generates a valid `capsule.manifest.yaml` and starter project.
  - `capsule validate` / `capsule validate --json` validates syntax, schema, and limits with exit codes per CLI spec.
  - `capsule publish` and `capsule publish --json` packages and triggers idempotent deployment.
  - `capsule share add --user <email> --role <role>` successfully grants access.
  - Never requires or logs raw secrets in terminal arguments.

---

### Task 0.11: Local Development Emulator (`capsule dev`)

- **Goal:** Implement `capsule dev` to start the local developer emulator providing a local SQLite instance and mock identity context.
- **Files / Modules Touched:**
  - `packages/cli/src/commands/dev.ts`
  - `packages/cli/src/emulator/index.ts`
  - `packages/cli/src/emulator/mock-identity.ts`
  - `packages/cli/tests/dev.test.ts`
- **Dependencies:** Task 0.6, Task 0.10.
- **Acceptance Criteria:**
  - Runs application locally with live reload.
  - Binds local SQLite database file in `.capsule/local.db`.
  - Injects development identity headers (`dev-user@example.com`, role `employee`).
  - Does not expose production credentials or require control-plane connectivity.

---

### Task 0.12: End-to-End "Prove the Loop" Integration Test

- **Goal:** Execute the full Phase 0 acceptance test verifying the complete workflow under 60 seconds.
- **Files / Modules Touched:**
  - `tests/e2e/phase0_loop.test.ts`
- **Dependencies:** All previous tasks (0.1 through 0.11).
- **Acceptance Criteria:**
  1. CLI runs `capsule init` on reference app.
  2. CLI runs `capsule validate --json` $\rightarrow$ passes.
  3. CLI runs `capsule publish` $\rightarrow$ publishes reference app and returns live URL.
  4. CLI runs `capsule share add --user colleague@example.com --role viewer`.
  5. Colleague browser request to live URL authenticates and receives HTTP 200 with rendered app within 60 seconds total elapsed time.
  6. Database persists state across consecutive requests.
