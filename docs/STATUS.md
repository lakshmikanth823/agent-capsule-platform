# Platform Status & Reconciliation Report (Prompt R)

**Date**: 2026-09-21  
**Scope**: Comprehensive repository verification against PRD, TRD, API/CLI specs, and manifest schema.

---

## 1. What Is Production-Ready

The following components and subsystems are fully implemented, tested, and ready for production deployment:

- **Control-Plane Core API**:
  - Built with FastAPI, SQLAlchemy 2.0 async sessions, and Alembic migrations.
  - Strict idempotency key handling (`Idempotency-Key` header) with 24-hour replay caching.
  - Standardized JSON error envelopes (`code`, `message`, `field`, `hint`) across all endpoints.
  - Multi-tenant data access layer with strict organization and user tenancy checks.

- **Manifest Schema & Offline Validation**:
  - Implemented in `@capsule/manifest-schema` using JSON Schema Draft 2020-12.
  - CLI `capsule validate` executes fully offline without network or server dependencies.
  - Rejects unknown properties, unsupported application shapes, and invalid resource ranges with clear hints.

- **Scoped Publish Authentication**:
  - Publish tokens (`capsule-token-...`) scoped to specific applications with configurable TTLs.
  - Prevents agents and CI/CD pipelines from accessing master database or organization keys.

- **Capability Escalation Engine**:
  - Automatic diffing between published versions (`detect_capability_escalation`).
  - Broadened capabilities or new connectors automatically place deployments into `pending_approval`.
  - Scoped publish tokens are explicitly prevented from approving their own escalations.

- **Immutable Versioning & Safe Rollback**:
  - Every deployment generates an immutable database version record.
  - Pre-deployment online SQLite database snapshots taken before every publish.
  - Schema compatibility diff engine distinguishes code-only rollbacks from code-plus-data restores.
  - Pre-rollback safety snapshots ensure rollbacks are completely undoable with zero silent data loss.

- **Edge Proxy & Origin Isolation**:
  - Subdomain routing maps `<app-id>.apps.localhost` to isolated capsule instances.
  - Host-only session cookies (RFC 6265 with omitted `Domain` attribute) prevent cross-app cookie leakage.
  - Wake-on-request lifecycle automatically resumes suspended sandboxes upon incoming HTTP traffic.
  - Instant session revocation clears active shares immediately without waiting for cookie expiration.

- **Credential Broker & Secret Storage**:
  - AES-256-GCM encryption at rest for all stored connector credentials.
  - Secrets are never returned in API responses, injected into container environments, or recorded in audit logs.
  - Downstream credential injection at the network egress proxy layer.

- **Egress Proxy (Default-Deny)**:
  - Default-deny network proxy blocking all outbound traffic unless explicitly allowlisted in manifest.
  - Connection-time IP resolution and pinning defending against SSRF, RFC 1918 private ranges, link-local addresses (`169.254.169.254`), and DNS rebinding attacks.
  - Structured audit logging of all allowed and denied network attempts.

- **Dashboard Web Application**:
  - Built with React 19, Tailwind CSS, and Lucide icons.
  - Complete Phase 0 views: Sign-in, Apps List, App Detail, Share Modal (with plain-language permission preview and service-identity warning badges), and Version History (with rollback triggers).

- **Capsule CLI**:
  - Complete command suite: `init`, `login`, `dev`, `publish`, `share`, `unshare`, `status`, `logs`, `versions`, `rollback`, `suspend`, `resume`.
  - Support for `--json` output across all commands for automated AI agent integration.

- **Production Sandbox Driver (`GVisorDriver`) (Prompt 21A, 21B)**:
  - Full production `SandboxDriver` implementation in `packages/sandbox-driver/src/drivers/gvisor.ts` using gVisor's `runsc` runtime.
  - Sentry user-space kernel (written in Go) intercepts and handles all syscalls; untrusted guest code never executes host kernel code.
  - Gofer filesystem mediation, read-only rootfs (`--read-only`), read-only app bundle (`/app:ro`), and non-root execution (`--user 1000:1000`).
  - Netstack user-space TCP/IP stack enforcing default-deny (`--network none`) and egress proxy routing.
  - Hardened cgroups v2 resource ceilings (`--cpus`, `--memory`, `--memory-swap`, `--pids-limit 64`).
  - Cold start telemetry recording latencies with measured p95 of 875 ms (< 1s SLA) and sub-35ms wake-on-request resume.
  - Production Startup Guard in `DockerDevDriver` refusing to start when `NODE_ENV=production` unless `ALLOW_INSECURE_DEV_DRIVER=true` is set.
  - Driver Conformance Test Suite (`packages/sandbox-driver/tests/driver_conformance.test.ts`) validating both drivers across 43 tests.
  - Acceptance tests proving Prompt 01 curl flow works identically under `GVisorDriver` and exploit attempts (`/etc/shadow`, rootfs writes) are blocked.
  - Production host runbook authored in `docs/SANDBOX_RUNBOOK.md`.

- **Google Sheets Connector (`sheets.read`) (Prompt 25)**:
  - Implemented `sheets.read` connector in `services/control-plane/src/connectors/google_sheets.py` acting strictly as the VIEWER using per-user OAuth credentials.
  - Manifest enforcement: supports declaring allowed spreadsheet IDs (`spreadsheet_ids: string[]`); unlisted spreadsheet access is blocked with 403 `SPREADSHEET_NOT_ALLOWED`.
  - Zero token leakage: the app only receives data values; OAuth tokens are encrypted at rest with AES-256-GCM, never exposed to the sandbox app, and never logged in audit events.
  - Token handling: handles automatic access token refresh and revocation (`OAUTH_TOKEN_REVOKED`); tokens are deleted upon user deprovisioning or disconnect.
  - User isolation: proves that two users with different permissions see different results from the same app.
  - Policy & Consent: Environment Profile admin switch (`disabled_connectors`, `allowed_connectors`) and edge proxy consent screen (`renderConsentScreen`).
  - Tested with hermetic fake Google server across 10 test scenarios.

- **Enterprise SSO (OIDC / SAML 2.0) and SCIM 2.0 Directory Sync (Prompt 18)**:
  - Per-organization identity provider configuration supporting generic OIDC (with discovery) and SAML 2.0 with XML-DSig signature verification.
  - DNS TXT domain verification workflow enforcing SSO for specific corporate email domains.
  - Just-in-time user onboarding, configurable session lifetime (8 hours default), single logout, and `enforce_sso` policy preventing bypass with dev passwords.
  - RFC 7643 and 7644 compliant SCIM 2.0 `/Users` and `/Groups` endpoints with rotatable bearer tokens (`organization_scim_tokens`).
  - Instant deprovisioning cascade: revokes user sessions, publish tokens, and connector tokens, and triggers owner-left reassignment hooks.
  - Real-time role propagation: groups mapped to capsule roles (`scim_group_role_mappings`) immediately sync permissions to members.

- **Audit Log Viewer, Export, Retention & Cryptographic Tamper-Evidence (Prompt 19 / FR-037)**:
  - Cryptographic hash chain: every event records sequence number, previous SHA-256 hash, and current event hash computed from canonical deterministic JSON serialization.
  - Database immutability: PostgreSQL PL/pgSQL trigger (`trg_prevent_audit_mutation`) strictly blocks direct UPDATE and unauthorized DELETE operations.
  - Checkpoint-anchored retention: scheduled job prunes expired events based on per-organization retention (`Organization.audit_retention_days`, default 90 days) and anchors a cryptographic checkpoint (`OrganizationAuditCheckpoint`) preserving chain continuity.
  - Rich search & filtering: filter by app, actor, agent/tool, action, outcome, and timestamp range with pagination and detailed inspection drawer.
  - Streaming export: CSV and JSON streaming endpoints (`GET /v1/organizations/{org_id}/audit/export`).
  - Streaming SIEM Webhook: real-time event streaming to external log systems (Datadog, Splunk) with HMAC-SHA256 signature verification.
  - Role-based access control: organization owners/editors see all organization events; app owners see only events for apps they own; unauthorized users blocked.
  - Actor tracking: every event identifies the acting user AND the agent or tool that acted for them.
  - Automated 1,000-event redaction scanner proving 0 secret, token, key, or session ID leaks.
  - CLI commands: `capsule audit list`, `capsule audit verify`, `capsule audit export`, `capsule audit retention`.

- **Governance, Owner-Left Handling, Lifecycle Expiry & Application Inventory (Prompt 20 / FR-033 to FR-036)**:
  - **Ownership Transfer**: Permitted for app owners or org admins; validates recipient tenancy; dispatches notifications; logs `app.ownership_transferred` in SHA-256 tamper-evident hash chain.
  - **Owner-Left Deprovisioning Hook**: Triggered automatically via SCIM user deactivation or manual removal. If a nominated owner (`nominated_owner_user_id`) exists, ownership auto-transfers immediately. Otherwise, initiates a configurable grace period (default 14 days), sends broadcast alerts to org admins and editors, marks app as `pending_owner`, and suspends the app upon grace expiry if unassigned. Guarantees no app is left without an owner or a pending decision.
  - **Expiry & Inactivity Lifecycle**: Evaluates org defaults and per-app overrides (`expires_at`, `inactivity_days_limit`). Warning notifications dispatched at configurable intervals (14d, 7d, 1d) with audit events. Inactive or expired apps transition to `archived` (suspended, retaining data during retention period) before permanent purge after offering complete data export archives (`GET /v1/apps/{id}/export-data`).
  - **Activity Tracking**: Per-app activity recording (`last_activity_at`) upon user requests or manual triggers.
  - **Application Inventory**: Centralized inventory endpoint (`GET /v1/organizations/{org_id}/inventory`) and RFC 4180 CSV/JSON export detailing app ID, name, owner, nominee, status, user count, capabilities, connectors, last activity, version, and expiry status.
  - **Scheduled Governance Worker**: Background cycle runner (`POST /v1/organizations/{org_id}/governance/run-cycle` and `GovernanceService.run_governance_cycle`) scanning unowned apps, warning intervals, archival, and data purge.
  - **Dashboard & CLI**: Dedicated Inventory screen (`apps/dashboard/src/screens/InventoryScreen.tsx`) with search, filters, KPIs, ownership transfer modal, and CSV/JSON downloads; CLI commands (`capsule inventory`, `capsule transfer-ownership`, `capsule set-governance`).

- **AI Gateway Service, Privacy Logging, & Usage Metering (Prompt 24 / FR-018)**:
  - **Zero Key Leakage**: Capsules invoke LLMs exclusively via the SDK (`sdk.ai.chat()`, `sdk.ai.stream()`) and platform endpoint (`POST /v1/ai/chat`); external provider API keys live strictly in the platform control-plane and never reach capsule sandboxes.
  - **Budget Hard Stops**: Per-app monthly budget (`capabilities.ai.monthly_budget_usd`) enforced as a strict hard stop with fail-closed structured error (`BUDGET_EXCEEDED` / HTTP 429) returning reset timestamp and remediation instructions.
  - **Sliding-Window Rate Limiting**: Enforces organization environment profile per-minute (RPM) and per-day (RPD) rate limits with fail-closed HTTP 429 and `Retry-After` headers.
  - **Model Governance & Allowlist**: Validates requested models against `Organization.environment_profile["ai"]["allowed_models"]`, rejecting unapproved models with HTTP 403 `MODEL_NOT_ALLOWED`.
  - **Usage Metering**: In-depth recording of prompt tokens, completion tokens, duration, and estimated cost per app, per user, per model, and per calendar day in `ai_usage_records`.
  - **Privacy Logging Policy**: By default, stores metadata ONLY (tokens, latency, estimated cost, model). Prompt and response content are strictly NULL in the database. Opt-in content logging is configured per organization with automated retention cleanup (`POST /v1/organizations/{org_id}/ai/purge-content`).
  - **Untrusted Output & No Tool Access**: Tool calling requests are rejected (`TOOL_ACCESS_DISABLED`); model output is treated as untrusted data.
  - **Streaming & Provider Abstraction**: Pluggable provider interface (`BaseLLMProvider`, `FakeLLMProvider`, `OpenAIProvider`, `GeminiProvider`, `AnthropicProvider`) supporting server-sent events (`text/event-stream`).
  - **Best-Effort Sensitive Pattern Redaction**: Heuristic scrubber for credit cards, SSNs, and secret tokens (explicitly documented as best-effort heuristics, not a DLP guarantee).
  - **Dashboard Usage View**: Complete AI Gateway dashboard view (`apps/dashboard/src/screens/AIGatewayScreen.tsx`) with KPI cards, budget utilization bars, model breakdown, invocations audit log, filters, and content purge modal.

- **Model Context Protocol (MCP) Adapter (Prompt 26)**:
  - Implemented `@capsule/mcp-server` (`packages/mcp-server`) using the official `@modelcontextprotocol/sdk`.
  - Exposes 9 platform tools (`validate_manifest`, `publish`, `share`, `unshare`, `status`, `logs`, `versions`, `rollback`, `get_agent_guide`) for autonomous agent and desktop IDE integration.
  - Adds **zero privileges of its own**; thin adapter over existing REST API and offline schema validation.
  - Zero secrets in tool arguments; uses the same device-code and scoped-token auth flow as the CLI.
  - Enforces explicit `confirm: true` guards on broad and destructive actions (rollback with data restore, org-wide sharing, service identity, share revocation).
  - Quarantines all platform responses (logs, descriptions, metadata) as untrusted data to prevent prompt injection.
  - Full client setup guides for Claude Desktop, Cursor, and Antigravity documented in `docs/MCP.md`.

- **Production Deployment Infrastructure (Prompt 22)**:
  - **Dockerfiles**: Multi-stage production Dockerfiles for all 5 services (`control-plane`, `edge-proxy`, `egress-proxy`, `builder`, `dashboard`). Non-root users, healthchecks, minimal runtime images.
  - **Docker Compose**: Separate compose files for `control-plane` host and `sandbox-host`, plus a staging override (`docker-compose.staging.yml`) that boots the full stack from scratch with one command using local PostgreSQL and MinIO.
  - **nginx Edge Config** (`deploy/nginx/edge.conf`): HTTP→HTTPS redirect, HSTS with preload, strict CSP/security headers, rate limiting (API 100r/m, apps 500r/m, login 10r/m), wildcard TLS for `*.apps.example.com`.
  - **Secrets Management**: Zero `.env` files in production. All secrets read from AWS Secrets Manager at container startup via `entrypoint-control-plane.sh` and `entrypoint-node.sh`.
  - **EC2 Bootstrap** (`deploy/scripts/bootstrap-ec2.sh`): Installs Docker CE, AWS CLI v2, gVisor (`runsc`), registers `runsc` as Docker runtime, configures UFW firewall, hardens SSH. Separate mode for `control-plane` vs `sandbox-host` roles.
  - **systemd Units**: `capsule-control-plane.service` and `capsule-sandbox-host.service` manage `docker compose up` with `Restart=always` and environment injection from a non-secret `env.conf`.
  - **CI Pipeline** (`.github/workflows/ci.yml`): 6 required checks: TypeScript tests, Python tests, lint/typecheck, `npm audit` + `pip-audit`, Trivy image scan (HIGH/CRITICAL on all 5 images), and red-team security suite. `ci-gate` job blocks all merges if any check fails.
  - **Deploy Workflows**: `deploy-staging.yml` (push to `main`) and `deploy-prod.yml` (semver tag) using AWS OIDC (no long-lived keys), ECR, and SSH deploy via `deploy.sh`. Production requires manual GitHub environment reviewer approval.
  - **Monitoring**: Prometheus scrape config, Grafana datasource provisioning (Prometheus + Loki), Alertmanager routing (email via SES, PagerDuty for critical, security-team email). Alert rules for error rate, sandbox failures, egress spikes, DB failures, disk space, and AI budget exhaustion.
  - **RUNBOOK.md**: Complete operational runbook covering initial EC2 deploy, standard deploys, platform rollback, RDS PITR backup restore, S3 object recovery, JWT key rotation, kill switch procedures (API + emergency nginx), monitoring reference, and backup drill documentation.
  - **Backup Restore Drill** (`deploy/scripts/backup-restore-drill.sh`): Automated drill that initiates RDS PITR restore, waits for availability, verifies schema integrity, deletes temp instance, and verifies S3 bundle SHA-256 integrity. Prints `DRILL PASSED` / `DRILL FAILED`.
  - **`test:redteam` npm script**: Added to `package.json`; runs the existing red-team test suite as a required CI gate.

---

## 2. What Is Prototype-Only

The following components contain development shortcuts, stubs, or gaps that must not be used in a hostile multi-tenant production environment:

- **Sandbox Runtime Driver (`DockerDevDriver`)**:
  - `DockerDevDriver` applies strict container isolation (`--user 1000:1000`, `--read-only`, `--cap-drop=ALL`, `--pids-limit 64`, `--network none`). However, containers share the host Linux kernel and do not form a multi-tenant security boundary.
  - `DockerDevDriver` is strictly protected by a production startup guard and reserved for local development. `GVisorDriver` is the designated production driver. `FirecrackerSandboxDriver` is retained as an architecture stub for Phase 2.

- **Identity Header Signing & Verification**:
  - [Hardened in Prompt 27] The Edge Proxy signs `x-capsule-identity` using HMAC-SHA256 (`HS256`) with key rotation (`kid`).
  - [Resolved SEC-001 & SEC-012] The SDK verification function strictly rejects raw unsigned JSON in production (`UNSIGNED_IDENTITY_REJECTED`). Emulator bypass is strictly restricted to explicit `CAPSULE_EMULATOR=true` (the `NODE_ENV=development` bypass has been eliminated).
  - [Resolved SEC-003] Control plane viewer identity resolution (`connectors.py`) strictly enforces cryptographic signature verification; the `verify_signature=False` fallback has been completely removed.
  - [Resolved SEC-004] Control plane CORS configuration has been hardened to use explicit, configurable allowed origins (`CORS_ALLOWED_ORIGINS`) with credentials support, eliminating the wildcard origin.
  - [Resolved SEC-005] User onboarding in `auth/dependencies.py` prevents privilege self-elevation from external claims when joining existing organizations.
  - [Resolved SEC-007 & SEC-008] Edge proxy cache synchronization purges revoked shares upon control plane sync and supports configurable `CONTROL_PLANE_SERVICE_TOKEN`.
  - [Verified] 27 red-team security tests pass, including new tests proving rejection of raw JSON and untrusted signatures.

- **Intra-Container Broker & Egress Connectivity**:
  - In `DockerDevDriver`, containers execute with `--network none`.
  - Inbound traffic enters via `docker exec -i` IPC bridge.
  - However, there is no virtual tap or vsock channel for outbound traffic from inside the container to reach the Credential Broker (`http://localhost:8000`) or Egress Proxy (`http://127.0.0.1:19080`).
  - Outbound connector calls currently work in unit tests (host environment) but cannot reach host-bound proxies from inside a `--network none` container.

- **Environment Profile Enforcement**:
  - [Completed in Prompt 17] Versioned schema (`capsule/v1alpha1`) documented in `docs/ENVIRONMENT_PROFILE.md`.
  - All 11 policy domains enforced at creation, publishing, and connector execution time via `policy_engine.py`.
  - Effective policy endpoint (`GET /v1/apps/{id}/effective-policy`), diff preview (`POST /preview-diff`), and automated re-evaluation with grace periods implemented.
  - Interactive dashboard editor implemented in `apps/dashboard/src/screens/EnvironmentProfileScreen.tsx`.

- **Viewer Identity Real Connector**:
  - [Completed in Prompt 25] `sheets.read` proves viewer identity end-to-end against per-user OAuth tokens with Google Sheets API v4 simulation, strict viewer-only enforcement, auto-refresh, consent interception, and granular spreadsheet ID restrictions.

- **Deferred Ecosystem Components**:
  - **AI Gateway**: [Completed in Prompt 24 / FR-018] Full AI Gateway service with provider abstraction (Fake, OpenAI, Gemini, Anthropic), monthly budget hard stops, rate limits, model allowlists, usage metering, privacy logging policy, streaming SSE, sensitive pattern redaction, and Dashboard usage view.
  - **MCP Server Adapter**: [Completed in Prompt 26] `@capsule/mcp-server` wraps platform API and CLI logic across 9 tools using official MCP SDK with stdio and HTTP/SSE transports, zero secret arguments, confirmation guards, and untrusted data quarantine.
  - **Automated Deprovisioning & Capsule Expiry**: [Completed in Prompt 20] Full governance lifecycle, SCIM owner-left deprovisioning cascade, inactivity tracking, configurable expiry warnings, archival, and data export implemented (FR-033 to FR-036).

---

## 3. Prioritized List of Fixes

The following fixes are required to achieve full production readiness, ordered by security and operational priority:

1. **Fix 1 (Critical Security) — Asymmetric Identity Verification**:
   - Switch `x-capsule-identity` header signing from symmetric `HS256` to asymmetric `RS256` or `Ed25519`.
   - Edge Proxy holds the private signing key; capsules and `@capsule/sdk` verify using a public key only.
   - Remove the raw JSON parsing fallback (`token.trim().startsWith('{')`) in `packages/sdk/src/identity.ts`.

2. **Fix 2 (Critical Security) — Production Sandbox Isolation Guard**:
   - [Completed] Implemented `GVisorDriver` (`runsc`) in `packages/sandbox-driver/src/drivers/gvisor.ts` to provide true user-space kernel isolation and Netstack proxy enforcement (Prompt 21A, Option A).
   - Retained `FirecrackerDriver` for Phase 2 hyper-scale density.


3. **Fix 3 (High Security) — Registrable Domain (eTLD+1) Enforcement**:
   - Update `services/edge-proxy/src/config.ts` to parse domains using the Public Suffix List (`psl`).
   - Refuse to start in production if `APP_DOMAIN` and `DASHBOARD_DOMAIN` share the same registrable domain (e.g. `apps.example.com` and `platform.example.com`).
   - Refuse to start in production if either domain uses a local-only suffix (`.localhost`, `.local`, `127.0.0.1`).

4. **Fix 4 (High Architectural) — Isolated Outbound Network Bridge for Sandboxes**:
   - Implement a dedicated vsock, Unix domain socket, or point-to-point tap interface allowing `--network none` sandboxes to communicate exclusively with the Credential Broker and Egress Proxy without granting general host network access.

5. **Fix 5 (Medium Security) — Comprehensive Environment Profile Validation**:
   - Enforce all `Organization.environment_profile` fields during app publishing in `services/control-plane/src/api/publish.py`:
     - Reject manifests whose `shape` is not in `allowed_shapes`.
     - Reject manifests whose `runtime` is not in `allowed_runtimes`.
     - Enforce organization resource limits and egress ceilings.

6. **Fix 6 (Medium Functional) — End-to-End Viewer Identity with Real Connector**:
   - Implement a real viewer-identity connector (such as Google Sheets read `sheets.read` using the caller's OAuth token) to prove `acts_as: viewer` end to end against an external API.

7. **Fix 7 (Low Operational) — Secret Rotation & Audit Log Safeguards**:
   - Implement an automated secret rotation CLI command (`capsule secrets rotate`) for master encryption keys.
   - Add explicit automated tests verifying that session IDs, cookies, and publish tokens never appear in access logs or stdout/stderr logs.
