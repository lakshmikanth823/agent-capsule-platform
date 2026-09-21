# Architectural Conflicts & Technical Gaps Analysis

**Document Status:** Awaiting User Decisions  
**Date:** 2026-09-21  
**Source Documents Analyzed:** `docs/TRD.md`, `docs/PRD.md`, `docs/api-cli-spec/`, `docs/backend-database-schema/`, `docs/manifest-spec/`, `docs/FRONTEND_DESIGN.md`, `docs/Software_Capsule_Architecture_Diagram.*`

Per the Project Rules:
> "If documents conflict, or something you need is missing, STOP and ask me. Do not invent requirements. Record every answer in docs/DECISIONS.md with the date."

This document catalogs every contradiction between specifications and every missing technical detail required before coding Phase 0.

---

## 1. Contradictions Between Documents

### Item 1.1: Resource Naming & REST Paths (`capsules` vs `apps`)
- **Contradiction:**
  - **`docs/TRD.md` (Section 4):** Uses `/v1/capsules`, `/v1/capsules/{id}`, `/v1/capsules/{id}/deploy`, `/v1/capsules/{id}/share`, `/v1/capsules/{id}/versions`.
  - **`docs/api-cli-spec/API_CLI_SPEC.md` & `openapi.yaml`:** Uses `/apps`, `/apps/{appId}`, `/apps/{appId}/publish`, `/apps/{appId}/shares`, `/apps/{appId}/versions`.
  - **`docs/backend-database-schema/backend_schema.sql`:** Tables are named `apps`, `app_versions`, `app_shares`.
  - **`docs/manifest-spec/MANIFEST_SPEC.md`:** Top-level fields are `id` and `name`.
- **Proposed Default:**
  - Standardize on `/v1/capsules` in the public API to match the product identity and TRD (Source of Truth #1).
  - In the database schema, table names can be `capsules` (or aliased from `apps`) with primary key `id` and unique `slug`/`capsule_key`.
- **Decision Needed from User:**
  Should the REST API and database entities be named `capsules` (matching TRD) or `apps` (matching OpenAPI spec)?

---

### Item 1.2: Publish Endpoint Action Verb (`/deploy` vs `/publish`)
- **Contradiction:**
  - **`docs/TRD.md` (Section 4):** Proposes `POST /v1/capsules/{id}/deploy`.
  - **`docs/api-cli-spec/` & `CLI_SPEC.md`:** Specifies `POST /apps/{appId}/publish` and CLI command `capsule publish`.
- **Proposed Default:**
  - Use `POST /v1/capsules/{id}/publish` as the primary endpoint so the API action verb directly mirrors the CLI command `capsule publish`, while accepting `POST /v1/capsules/{id}/deploy` as an alias if needed.
- **Decision Needed from User:**
  Should the deployment endpoint be `POST /v1/capsules/{id}/publish` or `POST /v1/capsules/{id}/deploy`?

---

### Item 1.3: Database Snapshot on Version 1 (`NOT NULL` constraint)
- **Contradiction / Dilemma:**
  - **`docs/TRD.md` (Section 12):** "A database snapshot MUST be created on every deployment."
  - **`docs/backend-database-schema/backend_schema.sql`:** `app_versions.db_snapshot_ref text NOT NULL`.
  - **Dilemma:** On initial deployment (Version 1), the application has never run, so no data exists yet.
- **Proposed Default:**
  - During Version 1 deployment, the platform initializes an empty, clean SQLite database file, takes its snapshot, and stores it as `capsules/{id}/snapshots/{snapshot_id}.sqlite` before activating the container. This ensures `db_snapshot_ref` is always valid and rollback to Version 1 cleanly restores the empty baseline.
- **Decision Needed from User:**
  Confirm that initial deployment (Version 1) creates and records an empty baseline SQLite snapshot.

---

## 2. Missing Technical Details & Gaps

### Item 2.1: Control Plane Implementation Language & Framework
- **Gap:**
  - `docs/TRD.md` Table 42 proposes:
    - Control API: `FastAPI/Python`
    - CLI: `TypeScript or Python`
    - Application runtime: `Node.js 22` (TypeScript)
    - SDK: TypeScript
  - However, in a monorepo, using TypeScript for the control plane (e.g., Fastify/Node.js) would allow sharing the JSON Schema validator (`packages/manifest-schema`) and TypeScript types directly between the Control Plane, CLI, SDK, and Edge Proxy without code duplication across Python and TypeScript.
- **Proposed Default:**
  - Adhere strictly to TRD Table 42:
    - **Control Plane API:** Python 3.12+ with `FastAPI`, `Pydantic v2`, and `SQLAlchemy`/`asyncpg`.
    - **CLI:** TypeScript (`Node.js 22`) with `commander` or `citty`.
    - **SDK:** TypeScript (`Node.js 22`).
    - **Edge Proxy:** TypeScript (`Node.js 22`) with `http-proxy` or Fastify.
  - For manifest validation in Python, use Python's `jsonschema` library loading the canonical `capsule.manifest.schema.json`.
- **Decision Needed from User:**
  Confirm whether Control Plane API should be Python (`FastAPI`) per TRD Table 42 or TypeScript (`Node.js 22`).

---

### Item 2.2: Sandbox Driver Implementation for Phase 0
- **Gap:**
  - TRD Section 9: "Sandbox decision: TBD. Evaluate Firecracker, gVisor, or equivalent."
  - The local development environment is Windows with Docker Desktop (WSL2 backend). Firecracker requires Linux KVM hardware virtualization.
  - Project Rule 9: "The sandbox is behind a `SandboxDriver` interface. Any development-only driver must be clearly named and documented as NOT a security boundary."
- **Proposed Default:**
  - Define an abstract `SandboxDriver` interface:
    ```typescript
    interface SandboxDriver {
      create(spec: SandboxSpec): Promise<SandboxInstance>;
      start(id: string): Promise<void>;
      stop(id: string): Promise<void>;
      destroy(id: string): Promise<void>;
      getHealth(id: string): Promise<HealthStatus>;
    }
    ```
  - For Phase 0 on Windows / Docker: Provide `DockerSandboxDriver` using Docker Desktop WSL2 backend with non-root execution, CPU/memory limits, read-only rootfs, and isolated bridge network.
  - Provide a `DevMockSandboxDriver` clearly documented as NOT a security boundary for unit tests.
  - Keep the interface ready to plug in `FirecrackerSandboxDriver` or `GVisorSandboxDriver` in production Linux environments.
- **Decision Needed from User:**
  Approve `DockerSandboxDriver` (WSL2 Docker backend) as the Phase 0 driver implementation.

---

### Item 2.3: Registrable Domain & Local Origin Isolation Strategy
- **Gap:**
  - TRD Section 16 & 55: "The exact registrable-domain strategy is TBD and requires browser-security review."
  - Security Invariant 5: "Applications are served from a different origin than the dashboard."
  - In local development, how should origins be structured?
- **Proposed Default:**
  - Per RFC 6761, all modern browsers treat `*.localhost` as loopback (`127.0.0.1`) and recognize subdomains as distinct browser origins.
  - We will use:
    - **Capsule Apps:** `http://<capsule-id>.localhost:8080/`
    - **Platform Dashboard & Control:** `http://localhost:8080/` (or `http://dashboard.localhost:8080/`)
  - This provides strict origin separation locally without requiring manual `/etc/hosts` edits or external DNS.
- **Decision Needed from User:**
  Confirm the local origin convention: `http://<capsule-id>.localhost:8080`.

---

### Item 2.4: Identity / Authentication Provider for Phase 0 & Automated Tests
- **Gap:**
  - TRD Section 15 & PRD Section 5 require Google/OIDC login.
  - However, automated integration tests and the 60-second Phase 0 acceptance test ("an agent publishes a small app with the CLI and a colleague opens it, in under 60 seconds") cannot depend on interactive Google browser login prompts or external cloud connectivity during automated test runs.
- **Proposed Default:**
  - Provide a standard OIDC JWT verification flow in the Edge Proxy.
  - Provide a configurable `MockOIDCProvider` in the control plane for local development and testing that issues signed JWTs for predefined identities (`owner@example.com`, `colleague@example.com`) without external network calls.
  - Production/staging configuration uses real Google OIDC discovery and JWKS verification.
- **Decision Needed from User:**
  Confirm using a built-in Mock OIDC provider for automated local tests and development mode.

---

### Item 2.5: SQLite Library in Blessed Node.js 22 Runtime SDK
- **Gap:**
  - TRD Section 7 specifies `Node.js 22 + TypeScript web application using the platform SDK`.
  - Node.js 22 includes experimental native `node:sqlite`, while `better-sqlite3` is the incumbent production standard.
- **Proposed Default:**
  - Use `better-sqlite3` inside `@capsule/sdk` for synchronous SQLite access with WAL mode enabled. If native module compilation on Windows is an issue in specific developer environments, provide a seamless fallback to `node:sqlite`.
- **Decision Needed from User:**
  Confirm `better-sqlite3` as the default SQLite library for `@capsule/sdk`.

---

### Item 2.6: Object Storage Driver for Phase 0
- **Gap:**
  - TRD Table 42 specifies "S3-compatible object storage".
  - Running MinIO locally introduces an additional dependency for simple Phase 0 test runs.
- **Proposed Default:**
  - Implement an abstract `ObjectStorageDriver` with:
    1. `LocalStorageDriver`: stores files directly in `.capsule/storage/` under the TRD-prescribed path structure (`capsules/{id}/artifacts/`, `snapshots/`).
    2. `S3StorageDriver`: uses AWS SDK S3 client compatible with MinIO and AWS S3.
  - Default to `LocalStorageDriver` for local Phase 0 CLI testing, switchable to `S3StorageDriver` via environment variable `STORAGE_DRIVER=s3`.
- **Decision Needed from User:**
  Confirm that `LocalStorageDriver` is approved for Phase 0 local execution.

---

### Item 2.7: Monorepo Package Management & Tooling
- **Gap:**
  - No specific package manager is dictated in `docs/TRD.md`.
- **Proposed Default:**
  - For Node.js / TypeScript: Use `pnpm` (or `npm`) with workspaces.
  - For Python (Control Plane): Use standard virtual environment (`venv`) with `pip` or `uv`.
- **Decision Needed from User:**
  Confirm preferred package manager (`pnpm` vs `npm`).

---

## Summary of Decisions Needed from User

| # | Topic | Proposed Default | User Decision |
|---|---|---|---|
| 1 | Resource Naming | Use `capsules` for API paths (`/v1/capsules`) and entities | [Pending User Approval] |
| 2 | Deployment Verb | Use `POST /v1/capsules/{id}/publish` | [Pending User Approval] |
| 3 | Version 1 Snapshot | Create empty baseline SQLite snapshot on Version 1 | [Pending User Approval] |
| 4 | Control Plane Language | Python (`FastAPI`) per TRD Table 42 | [Pending User Approval] |
| 5 | Sandbox Driver | `DockerSandboxDriver` (Docker Desktop WSL2) for Phase 0 | [Pending User Approval] |
| 6 | Local Origin Strategy | `http://<capsule-id>.localhost:8080` | [Pending User Approval] |
| 7 | OIDC for Tests | Built-in Mock OIDC provider for tests/local dev | [Pending User Approval] |
| 8 | SQLite Library | `better-sqlite3` in `@capsule/sdk` | [Pending User Approval] |
| 9 | Storage Driver | `LocalStorageDriver` default for local Phase 0 | [Pending User Approval] |
| 10 | Package Manager | `pnpm` workspaces | [Pending User Approval] |
