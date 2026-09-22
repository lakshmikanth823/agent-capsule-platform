# Product Requirements Document (PRD)

## Software Capsule Platform

**Document Version:** 0.2  
**Status:** Draft for review  
**Last Updated:** 2026-09-21  
**Product Type:** Secure infrastructure platform for agent-built small software

---

## 1. Executive Summary

The Software Capsule Platform makes small, purpose-built software easy to publish, secure, share, update, and operate.

The platform is designed for software generated or modified by external AI agents such as Claude, Codex, Cursor, custom agents, or internal automation. The platform is not itself an AI coding agent. It provides a controlled target that agents can build against and a secure environment in which generated applications can run.

The central product object is a **Software Capsule**: an application artifact plus a machine-readable manifest describing its runtime, capabilities, identity requirements, resource limits, sharing rules, and version.

The platform provides:

- agent-facing API and CLI
- optional MCP adapter
- constrained application shape
- strong runtime isolation
- per-application origin isolation
- platform-managed authentication and identity
- sharing and application roles
- per-Capsule SQLite storage
- versioning and safe rollback
- capability-based permissions
- default-deny outbound networking
- credential brokering
- organization Environment Profiles
- governance and audit
- observability
- suspension and revocation controls

The core product promise is:

> **An agent can turn a small software idea into a secure, shareable working application without the user having to operate cloud infrastructure.**

---

# 2. Problem Statement

AI agents have significantly reduced the effort required to create small, specialized software. Teams and individuals can now generate applications for workflows, tracking, prototypes, internal tools, operational dashboards, and other narrow use cases.

The remaining difficulty is operating these applications safely.

Traditional cloud platforms are optimized for larger applications and introduce infrastructure concerns such as:

- deployment configuration
- networking
- authentication
- identity
- secrets
- permissions
- databases
- scaling
- monitoring
- application isolation

For small software, this operational complexity can be disproportionate to the value of the application.

Generated code also introduces additional security concerns because the platform cannot assume that application code is trustworthy.

The product therefore needs to solve a different problem:

> **How can arbitrary small applications created by agents be deployed and shared as easily as a document while maintaining strong isolation, controlled permissions, identity, networking, credentials, data protection, and governance?**

---

# 3. Product Vision

Make small software behave operationally like a shared document:

1. Describe what is needed.
2. An existing agent builds the application.
3. The agent validates it locally.
4. The agent publishes it.
5. The platform creates a secure Software Capsule.
6. A working application URL becomes available.
7. The owner shares it with colleagues.
8. Users authenticate through the platform.
9. The application runs in an isolated environment.
10. Updates create immutable versions.
11. Capability increases require human approval.
12. The owner can suspend, restore, export, or roll back the application.

---

# 4. Users and Personas

## 4.1 Individual Builder

Creates small software for personal use.

Needs:

- simple publishing
- low operational overhead
- secure defaults
- personal authentication
- data portability
- predictable limits

## 4.2 Team Builder

Creates software for a small team or department.

Needs:

- sharing
- application roles
- team identity
- controlled connectors
- versioning
- rollback
- auditability

## 4.3 Organization Administrator

Controls the environment in which team applications run.

Needs:

- organization policies
- connector restrictions
- identity integration
- Environment Profiles
- audit
- application inventory
- suspension and revocation
- ownership/deprovisioning controls

## 4.4 External Agent / Automation

Creates, validates, updates, and publishes applications through the platform.

Needs:

- stable API
- CLI
- machine-readable manifest schema
- deterministic validation
- readable documentation
- safe authentication
- idempotent publishing
- clear machine-readable errors

---

# 5. Release Structure

The previous MVP/Phase-0 scope is separated into distinct releases.

| Release                     | Scope                                                                                                                             |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Alpha / Phase 0**         | Publish, secure sandbox, Google/OIDC login, sharing, SQLite, basic origin isolation, validation                                   |
| **MVP / Phase 0 + 1**       | Capabilities, egress control, roles, credential broker, versions, snapshots, rollback, quotas, kill switch                        |
| **Company-ready / Phase 2** | Environment Profiles, enterprise SSO, SCIM, governance, audit, connector administration                                           |
| **Scale / Phase 3**         | Expiry, ownership transfer, previews, budgets, PostgreSQL capability, additional runtimes, private data planes, templates/forking |

Every functional requirement below has a **Priority** and **Phase**.

---

# 6. Goals

## 6.1 Primary Goals

1. Publish agent-built small software without requiring users to manage cloud infrastructure.
2. Provide strong isolation for untrusted generated application code.
3. Make applications easy to share with authorized users.
4. Provide platform-managed identity and application roles.
5. Make application permissions explicit and enforceable.
6. Prevent unauthorized outbound network access by default.
7. Prevent applications from receiving raw credentials.
8. Support safe application updates and rollback.
9. Make application behavior governed by organization policy.
10. Provide sufficient observability and auditability for operating the platform.
11. Keep the application target constrained enough for agents to build against reliably.

## 6.2 Non-Goals

The platform will not initially:

- build applications using its own AI agent
- replace Claude, Codex, Cursor, or other coding agents
- provide Kubernetes as the application deployment abstraction
- provide multiple runtime tiers based on application size
- provide a marketplace
- operate a general-purpose arbitrary cloud infrastructure platform
- provide enterprise-scale analytics as a primary product
- use security scanning as the primary runtime security boundary
- require approval for every normal application update

---

# 7. Core Product Concept: Software Capsule

A Software Capsule is the platform's fundamental application object.

A Capsule contains or references:

- Capsule ID
- application name
- application artifact
- manifest
- runtime
- application shape
- capabilities
- application roles
- sharing policy
- environment policy reference
- version
- data snapshot reference
- ownership
- lifecycle state
- resource limits

The Capsule does **not** contain platform identity infrastructure, credentials, or unrestricted network access.

---

# 8. Blessed Application Shape

## 8.1 Alpha Shape

The first supported application shape is:

> **Node.js + TypeScript web application using a small supported server framework and the Software Capsule Platform SDK.**

The platform provides a blessed application template and SDK.

The initial shape should support:

- HTTP requests
- HTML/UI delivery
- API routes
- platform identity
- SQLite
- files
- declared capabilities
- controlled outbound requests

Other languages and application shapes are deferred.

## 8.2 Reason for Constraint

A constrained application shape allows:

- higher agent success rates
- deterministic builds
- smaller runtime surface
- easier sandboxing
- simpler documentation
- predictable resource requirements
- faster cold starts
- easier security testing

---

# 9. User Journey

### Step 1 — Describe

The user describes the required application to an existing AI agent.

### Step 2 — Build

The agent creates an application against the Capsule SDK and manifest schema.

### Step 3 — Validate

The agent runs:

```bash
capsule validate
```

and optionally:

```bash
capsule dev
```

### Step 4 — Publish

The agent runs:

```bash
capsule publish
```

### Step 5 — Policy Validation

The platform validates:

- manifest
- application shape
- runtime
- capabilities
- resource limits
- environment policy
- security constraints

### Step 6 — Deploy

The application is deployed into a strong sandbox.

### Step 7 — Share

The owner selects authorized users or groups.

### Step 8 — Use

A user opens the application URL and authenticates through the platform.

### Step 9 — Update

The agent creates a new immutable version.

### Step 10 — Review Capability Changes

New or broadened capabilities require human owner approval.

### Step 11 — Roll Back

The owner can perform code-only rollback or an explicitly confirmed code + data restore.

---

# 10. Capsule Lifecycle State

A Capsule uses explicit lifecycle states:

```text
DRAFT
  ↓
VALIDATING
  ↓
PUBLISHED
  ↓
RUNNING
  ↓
SUSPENDED
  ↓
ARCHIVED
```

Deployment states:

```text
PENDING
VALIDATING
APPROVAL_REQUIRED
DEPLOYING
ACTIVE
FAILED
ROLLED_BACK
```

Every state transition is recorded where audit is available.

---

# 11. Functional Requirements

## FR-001 — Application Publishing

**Priority:** Must  
**Phase:** Alpha

The platform MUST allow an authenticated agent or user to publish a valid application through the API or CLI.

### Acceptance Criteria

**Given** a valid application and manifest  
**When** the user or agent runs `capsule publish`  
**Then** the platform creates or updates the Capsule and returns a deployment result.

Publishing MUST be idempotent using a client-provided request/idempotency key.

---

## FR-002 — Capsule Manifest

**Priority:** Must  
**Phase:** Alpha

Every Capsule MUST have a machine-readable manifest.

The manifest MUST describe:

- ID
- name
- application shape
- runtime
- capabilities
- roles
- resource limits
- sharing
- egress policy
- schedules when supported
- version metadata

The manifest MUST be validated against a published JSON Schema.

---

## FR-003 — Blessed Application Shape

**Priority:** Must  
**Phase:** Alpha

The platform MUST support one blessed Node.js/TypeScript web application shape.

Unsupported application shapes MUST be rejected with a machine-readable error.

---

## FR-004 — Strong Runtime Isolation

**Priority:** Must  
**Phase:** Alpha

Every Capsule MUST execute in a strong sandbox suitable for untrusted generated code.

The implementation MUST provide:

- process/runtime isolation
- non-root execution
- resource limits
- syscall restrictions
- filesystem isolation
- network policy enforcement

Docker alone MUST NOT be treated as the security boundary.

The sandbox implementation will be selected through a technical spike evaluating options such as Firecracker and gVisor.

---

## FR-005 — Application Origin Isolation

**Priority:** Must  
**Phase:** Alpha

Each Capsule MUST have an isolated application origin.

The platform MUST:

- allocate a reserved application name
- prevent hostname collisions
- attribute each hostname to its Capsule and owner
- prevent one Capsule from impersonating another
- prevent shared authentication cookies between Capsules

The exact domain strategy will be determined during security design.

---

## FR-006 — Authentication

**Priority:** Must  
**Phase:** Alpha

The platform MUST provide authentication through Google/OIDC.

The platform MUST support a central authentication service and per-application login handshake.

Enterprise SAML is deferred to Phase 2.

---

## FR-007 — Identity Context

**Priority:** Must  
**Phase:** Alpha

After authentication, the platform MUST provide the application with a signed identity context.

The identity context MUST include, where applicable:

- user ID
- organization ID
- groups
- application roles
- token expiry
- audience

The application MUST verify:

- signature
- issuer
- audience
- expiry

Signing keys MUST support rotation.

---

## FR-008 — Application Roles

**Priority:** Must  
**Phase:** MVP

Applications MAY define roles such as:

- Employee
- Manager
- HR
- Reviewer
- Administrator

Application roles control in-application behavior.

Application roles MAY map from identity-provider groups.

---

## FR-009 — Platform Roles

**Priority:** Must  
**Phase:** MVP

The platform MUST support:

- Owner
- Editor
- User

Platform roles control Capsule management.

Only Owner and authorized Editor users MAY modify sharing and role assignments.

---

## FR-010 — Sharing

**Priority:** Must  
**Phase:** Alpha

Owners MUST be able to share a Capsule with:

- individual organization users
- groups
- organization members

External/guest users are out of scope for Alpha and default to disabled.

Permission revocation MUST take effect within seconds under normal platform operation.

---

## FR-011 — Permission Preview

**Priority:** Must  
**Phase:** MVP

The sharing interface MUST display all capabilities granted to the application in plain language.

Service identity MUST be clearly highlighted.

Example:

```text
This application can:
- Read Google Sheets as the signed-in user.
- Post messages to the configured Slack channel using a service identity.
- Store up to 200 MB of files.
```

---

## FR-012 — SQLite Per Capsule

**Priority:** Must  
**Phase:** Alpha

Each Capsule MUST have its own SQLite database.

The platform MUST enforce:

- database size limit
- one active database writer/active application instance at a time unless the supported application shape provides a safe mechanism
- backup/snapshot behavior
- storage quotas

PostgreSQL is deferred to a later capability for applications that outgrow SQLite.

---

## FR-013 — Database Snapshots

**Priority:** Must  
**Phase:** MVP

The platform MUST create a database snapshot on every deployment.

Snapshots MUST support:

- restore
- cloning
- preview
- export
- rollback recovery

A snapshot MUST be taken immediately before a data-changing rollback.

---

## FR-014 — Safe Rollback

**Priority:** Must  
**Phase:** MVP

The platform MUST distinguish between:

1. code-only rollback
2. code + data restore

### Code-only rollback

If the existing database schema remains compatible, the platform SHOULD default to restoring application code while preserving current data.

### Code + data restore

The platform MUST require explicit confirmation.

The confirmation MUST show:

- affected data time range
- expected record/data loss
- target version
- recovery snapshot availability

The pre-rollback snapshot MUST make the rollback itself undoable.

---

## FR-015 — Object/File Storage

**Priority:** Must  
**Phase:** MVP

Capsules MAY use platform-managed object storage for uploaded files.

File size and total storage limits MUST be enforced.

---

## FR-016 — Capability Declaration

**Priority:** Must  
**Phase:** MVP

Applications MUST explicitly declare requested capabilities.

Examples:

```yaml
capabilities:
  db: sqlite
  files:
    max_mb: 200
  ai:
    monthly_budget_usd: 5
  connectors:
    - sheets.read
```

---

## FR-017 — Capability Enforcement

**Priority:** Must  
**Phase:** MVP

Capabilities MUST be enforced by platform security boundaries.

The SDK MUST NOT be treated as the security boundary.

Enforcement MUST occur at relevant sandbox, identity, storage, and network layers.

An application MUST NOT gain an undeclared capability by bypassing the SDK.

---

## FR-018 — AI Capability

**Priority:** Should  
**Phase:** MVP

If enabled, AI access MUST use approved platform models/providers.

The platform MUST define:

- permitted models
- spending limits
- who pays
- per-Capsule budget
- request limits
- prompt/response logging policy
- retention policy

Raw provider credentials MUST NOT be exposed to applications.

---

## FR-019 — Default-Deny Egress

**Priority:** Must  
**Phase:** MVP

All outbound network access MUST be denied unless explicitly permitted.

### Acceptance Criteria

**Given** an application with:

```yaml
egress: []
```

**When** the application requests `https://example.com`

**Then** the request MUST fail and the platform MUST record the application, destination, timestamp, and result.

---

## FR-020 — Egress Allowlist

**Priority:** Must  
**Phase:** MVP

Applications MAY request specific outbound destinations.

The application manifest MUST never widen the organization's Environment Profile policy.

The effective policy MUST be:

```text
Effective Policy =
Organization Policy
∩
Application Policy
```

---

## FR-021 — SSRF Protection

**Priority:** Must  
**Phase:** MVP

The egress system MUST protect against:

- private IP access
- loopback access
- cloud metadata endpoints
- DNS rebinding
- IPv4/IPv6 bypasses
- encoded IP representations
- redirects to prohibited destinations

DNS resolution and destination validation MUST be performed by trusted platform infrastructure.

---

## FR-022 — Network Logging

**Priority:** Must  
**Phase:** MVP

The platform MUST record security-relevant outbound requests.

Logs SHOULD include:

- Capsule
- user/agent identity where available
- destination
- timestamp
- allow/deny decision
- policy reason

---

## FR-023 — No Raw Secrets

**Priority:** Must  
**Phase:** MVP

Applications MUST NOT receive raw organization or connector credentials.

---

## FR-024 — Credential Broker

**Priority:** Must  
**Phase:** MVP

Connector access MUST flow through a credential broker.

Flow:

```text
Capsule
  ↓
Capability Broker
  ↓
Policy Check
  ↓
Credential Broker
  ↓
Egress Proxy
  ↓
External Connector
```

---

## FR-025 — Viewer Identity Default

**Priority:** Must  
**Phase:** MVP

Connector access MUST default to acting as the current signed-in viewer when supported.

---

## FR-026 — Service Identity

**Priority:** Must  
**Phase:** MVP

Service identity access MUST require explicit configuration and authorization.

The sharing/permission interface MUST clearly identify service-identity capabilities.

---

## FR-027 — Environment Profiles

**Priority:** Must  
**Phase:** Company-ready

Organizations MUST be able to define Environment Profiles controlling:

- application shapes
- runtimes
- capabilities
- connectors
- sharing
- egress
- AI budgets
- resource limits
- identity requirements
- security settings

---

## FR-028 — Policy Validation

**Priority:** Must  
**Phase:** Company-ready

A Capsule MUST be validated against the effective Environment Profile before deployment.

The application manifest MAY narrow organization policy but MUST NOT widen it.

Example:

```json
{
  "error": "capability_not_allowed",
  "capability": "slack.post",
  "reason": "Organization policy prohibits Slack connectors"
}
```

---

## FR-029 — Application Versions

**Priority:** Must  
**Phase:** MVP

Every successful deployment MUST create an immutable application version.

Each version MUST have:

- version ID
- publisher
- publish timestamp
- change description
- artifact reference
- manifest reference
- database snapshot reference

---

## FR-030 — Rollback

**Priority:** Must  
**Phase:** MVP

Owners MUST be able to roll back to a previous application version.

The system MUST present the rollback type and data impact before execution.

---

## FR-031 — Version History

**Priority:** Must  
**Phase:** MVP

The platform MUST display:

- version
- publisher
- publish time
- status
- capability changes
- rollback availability

---

## FR-032 — Conditional Capability Approval

**Priority:** Must  
**Phase:** MVP

Normal updates that preserve existing capabilities MAY deploy automatically.

A deployment MUST require human owner approval when it:

- introduces a new capability
- broadens an existing capability
- introduces service identity
- requests a newly restricted connector
- violates organization policy

An agent's publish credential MUST NEVER be able to approve its own capability escalation.

---

## FR-033 — Ownership

**Priority:** Must  
**Phase:** MVP

Every Capsule MUST have an owner.

Ownership MUST be visible to authorized users.

---

## FR-034 — Ownership Deprovisioning

**Priority:** Should  
**Phase:** Phase 3

If an owner is deprovisioned, the platform MUST automatically apply an organization policy such as:

- suspend
- transfer
- designate an administrator
- archive

The application MUST NOT become silently unmanaged.

---

## FR-035 — Expiry

**Priority:** Should  
**Phase:** Phase 3

Capsules MAY have an expiry date.

Expired applications SHOULD enter a controlled lifecycle such as warning → suspension → archive.

---

## FR-036 — Application Inventory

**Priority:** Must  
**Phase:** Company-ready

Organization administrators MUST be able to view:

- Capsule
- owner
- state
- version
- capabilities
- connectors
- last activity
- policy status

---

## FR-037 — Audit Log

**Priority:** Must  
**Phase:** Company-ready

The platform MUST audit security and governance actions including:

- creation
- publishing
- updating
- rollback
- sharing
- permission changes
- capability approvals
- connector access
- policy changes
- ownership changes
- suspension
- credential revocation

Audit records MUST identify:

- acting user
- agent/tool where applicable
- Capsule
- action
- timestamp
- result

Audit records MUST have tamper-resistant storage, defined retention, and export capability.

---

## FR-038 — Kill Switch

**Priority:** Must  
**Phase:** MVP

The Capsule owner, authorized organization administrator, or platform security system MUST be able to immediately suspend a Capsule.

Suspension MUST prevent new application requests from executing.

---

## FR-039 — Connector Revocation

**Priority:** Must  
**Phase:** MVP

An organization administrator MUST be able to disable a connector globally.

Connector revocation MUST invalidate future access without requiring application code changes.

---

## FR-040 — Publish Token Revocation

**Priority:** Must  
**Phase:** MVP

The platform MUST support mass revocation of publish credentials/tokens.

---

## FR-041 — Resource Quotas

**Priority:** Must  
**Phase:** MVP

The platform MUST enforce quotas for:

- number of Capsules per user/org
- CPU
- memory
- database size
- file/blob storage
- request duration
- request rate
- egress bytes
- AI spend

The platform MUST define behavior when a quota is reached.

Recommended lifecycle:

```text
Warn → Throttle → Require graduation/upgrade
```

The platform MUST NOT silently corrupt or lose application data because of a quota.

---

## FR-042 — Local Development Emulator

**Priority:** Must  
**Phase:** Alpha

The platform MUST provide:

```bash
capsule dev
```

The local environment SHOULD emulate:

- SQLite
- identity context
- files
- capabilities
- supported SDK behavior

---

## FR-043 — Validation / Dry Run

**Priority:** Must  
**Phase:** Alpha

The CLI MUST provide:

```bash
capsule validate
capsule publish --dry-run
```

Validation MUST detect:

- invalid manifest
- unsupported runtime
- invalid application shape
- unavailable capability
- invalid resource limits
- invalid connector configuration
- policy conflicts

---

## FR-044 — Agent Documentation

**Priority:** Must  
**Phase:** Alpha

The platform MUST provide machine-readable agent documentation, such as:

- API documentation
- manifest JSON Schema
- SDK documentation
- CLI documentation
- agent-oriented instruction file such as `llms.txt` or an equivalent skill specification

---

## FR-045 — Secure Agent Authentication

**Priority:** Must  
**Phase:** Alpha

The platform MUST support device-code or OAuth-based authentication for interactive agent workflows.

Agents MUST NOT require users to paste long-lived platform secrets into prompts.

---

## FR-046 — Scheduled Execution

**Priority:** Deferred  
**Phase:** Phase 3

Scheduled jobs are deferred from Alpha/MVP unless a critical product use case requires them.

When implemented, schedules MUST support:

- wake-on-schedule
- authenticated execution
- resource limits
- retry behavior
- failure logging
- audit records

---

# 12. Authentication and Origin Security

The authentication flow is:

```text
User
 ↓
Capsule URL
 ↓
Edge Proxy
 ↓
Central Identity Provider
 ↓
Authentication
 ↓
Token Exchange
 ↓
Capsule-specific identity context
 ↓
Capsule
```

Each Capsule MUST have an application-specific audience.

Session cookies MUST be host-isolated. The implementation SHOULD use host-only or `__Host-` cookies where applicable.

The platform MUST ensure that authentication state cannot be reused by another Capsule.

The exact domain/registrable-domain strategy will be finalized through security review.

---

# 13. Permission Model

Two permission systems exist.

## Platform Roles

Control management of the Capsule:

- Owner
- Editor
- User

## Application Roles

Control application behavior:

- Employee
- Manager
- HR
- etc.

A single sharing workflow SHOULD assign platform access while application roles are derived from configured mappings such as identity-provider groups.

Only authorized platform users can change role assignments.

---

# 14. Data Model

## 14.1 Platform Metadata

The control plane stores:

- users
- organizations
- Capsules
- versions
- manifests
- ownership
- sharing
- policy
- audit metadata
- connector configuration

A relational metadata database such as PostgreSQL is appropriate for the control plane.

## 14.2 Capsule Data

Each Capsule uses its own SQLite database by default.

## 14.3 Object Storage

Object storage is used for:

- application artifacts
- snapshots
- uploaded files
- exports

---

# 15. Data Protection

The platform MUST provide:

- encryption in transit
- encryption at rest
- access-controlled backups
- defined deletion period after Capsule removal
- application/data export
- recovery snapshots
- defined RPO/RTO

### Initial target

The exact RPO/RTO values are a product decision and MUST be finalized before production launch.

Alpha may use documented best-effort recovery targets.

---

# 16. Export and Portability

Users MUST be able to export:

- application artifact
- manifest
- SQLite database
- uploaded files
- version metadata
- configuration that is safe to export

The export MUST be sufficient to allow migration away from the platform.

---

# 17. Build and Dependency Security

Application builds MUST occur in an isolated build environment.

The build system SHOULD:

- pin dependencies where possible
- enforce dependency size/resource limits
- reject prohibited packages according to policy
- record dependency metadata
- prevent build processes from accessing production credentials
- prevent build processes from bypassing network policy

Security scanning MAY produce warnings.

Security scanning MUST NOT be treated as the primary runtime security boundary.

---

# 18. Content Security

Applications MUST use HTTPS.

The platform SHOULD provide secure default headers including:

- Content Security Policy
- HSTS
- secure cookie attributes
- frame restrictions as appropriate
- MIME sniffing protections

Applications MUST NOT be able to modify platform-level security headers in ways that weaken Capsule isolation.

---

# 19. Deployment Behavior

A publish operation follows:

```text
Agent
 ↓
API / CLI
 ↓
Manifest Validation
 ↓
Application Validation
 ↓
Environment Policy Check
 ↓
Capability Change Check
 ↓
Approval if Required
 ↓
Build
 ↓
Snapshot
 ↓
Sandbox Deployment
 ↓
Health Check
 ↓
Active Version
```

If deployment fails:

- the previous active version remains available where possible
- the failed version is recorded
- the failure reason is returned
- no partial version becomes active

---

# 20. Capability Escalation Flow

Example:

### Version 1

```yaml
capabilities:
  connectors:
    - sheets.read
```

### Version 2

```yaml
capabilities:
  connectors:
    - sheets.read
    - slack.post
```

The platform detects the new capability.

The deployment enters:

```text
APPROVAL_REQUIRED
```

The owner sees:

```text
New permission requested:
Slack — send messages

Identity:
Service identity

Reason:
Application requests permission to post weekly leave summaries.
```

The agent cannot approve this request.

---

# 21. Observability

MVP observability MUST provide:

- Capsule state
- request count
- response status
- errors
- runtime logs
- deployment status
- resource quota status
- security-relevant egress events

Advanced metrics and enterprise observability integrations are deferred.

---

# 22. Reliability Requirements

The platform MUST:

- preserve the previous active version if deployment fails
- create snapshots before destructive data operations
- support restoration from snapshots
- prevent partial publication
- record failed deployments
- support application suspension

RPO and RTO targets MUST be finalized before production release.

---

# 23. Performance Requirements

Initial targets:

| Metric                       | Target                               |
| ---------------------------- | ------------------------------------ |
| Publish → working URL        | p95 < 30 seconds for reference app   |
| Share link → first render    | < 60 seconds with active IdP session |
| Cold start                   | p95 < 2 seconds                      |
| Reference application bundle | < 5 MB                               |
| Idle compute                 | Near-zero / storage-dominant         |

The reference application MUST be clearly defined before benchmarking.

---

# 24. Security Requirements

All generated application code MUST be treated as untrusted.

Required controls:

- strong sandbox
- non-root execution
- resource limits
- syscall restrictions
- filesystem isolation
- default-deny egress
- egress proxy
- SSRF protection
- separate application origins
- isolated authentication state
- capability enforcement
- credential broker
- no raw secrets
- secure build environment
- secure publish credentials
- audit
- kill switch
- connector revocation
- quotas
- encryption
- secure headers

Security tests MUST include adversarial applications attempting:

- unauthorized filesystem access
- cross-Capsule data access
- cross-origin access
- credential extraction
- unauthorized egress
- SSRF
- DNS rebinding
- IPv6 bypass
- resource exhaustion
- capability escalation
- metadata endpoint access

---

# 25. MVP Scope

## Must Have — Alpha

- API
- CLI
- Capsule manifest
- JSON Schema
- blessed Node.js/TypeScript application shape
- `capsule dev`
- `capsule validate`
- dry-run publishing
- strong sandbox
- application origin isolation
- Google/OIDC authentication
- platform identity
- sharing
- SQLite per Capsule
- basic storage quotas
- secure agent authentication
- agent documentation

## Must Have — MVP

- capabilities
- capability enforcement
- capability escalation approval
- default-deny egress
- egress allowlist
- SSRF protection
- credential broker
- viewer identity
- service identity
- application roles
- platform roles
- versions
- snapshots
- safe rollback
- kill switch
- connector revocation
- publish-token revocation
- quotas
- encryption
- export
- basic audit/security logging

## Must Have — Company-ready

- Environment Profiles
- enterprise SSO
- SCIM
- organization inventory
- governance
- audit retention/export
- organization connector administration
- ownership/deprovisioning policy

## Should Have — Later

- scheduled execution
- expiry
- ownership transfer
- previews
- PostgreSQL capability
- additional runtimes
- templates
- forking
- private/VPC data plane
- advanced budgets
- advanced analytics

## Won't Have

- marketplace
- Kubernetes as the product abstraction
- runtime tiers
- mandatory approval for every update
- built-in AI coding agent
- Postgres database per Capsule
- security scanning as the primary security boundary

---

# 26. Roadmap

## Phase 0 — Prove the Core Loop

### Deliver

- API
- CLI
- blessed application shape
- manifest
- validation
- local emulator
- sandbox
- application origin
- Google/OIDC login
- sharing
- SQLite

### Exit Criteria

A reference application can be:

> built → validated → published → opened by a colleague

with a working URL in under 60 seconds after publish under defined test conditions.

---

## Phase 1 — Make It Safe

### Deliver

- capability system
- capability enforcement
- egress proxy
- default-deny networking
- SSRF protection
- roles
- credential broker
- versions
- snapshots
- safe rollback
- kill switch
- quotas
- origin/session security

### Exit Criteria

The security test suite demonstrates that a deliberately malicious application cannot:

- access another Capsule's data
- access another Capsule's session
- bypass egress policy
- retrieve platform credentials
- escalate capabilities without approval
- escape the runtime boundary

---

## Phase 2 — Company-ready

### Deliver

- Environment Profiles
- enterprise SSO
- SCIM
- audit
- organization inventory
- connector administration
- ownership/deprovisioning controls

### Exit Criteria

An administrator can restrict:

- capabilities
- connectors
- sharing
- egress
- resource limits

without modifying application source code.

---

## Phase 3 — Scale

### Deliver

- expiry
- ownership transfer
- scheduled jobs
- previews
- PostgreSQL capability
- additional runtimes
- templates
- forking
- private/VPC data plane

### Exit Criteria

The platform can support a large collection of small applications with near-zero idle compute and controlled lifecycle management.

The exact scale target will be finalized after Alpha performance measurements.

---

# 27. Success Metrics

## Product Metrics

### North Star

> **Weekly Active Capsules with at least one non-owner viewer.**

This measures whether small software is actually being created and shared.

### Supporting Metrics

- publish-to-working-URL p95
- first-attempt agent publish success rate
- weekly active Capsules
- percentage of Capsules with non-owner activity
- percentage of Capsules with an active owner
- rollback frequency
- Capsule suspension frequency
- connector usage
- average idle resource cost

### Initial Hypothesis

At least **80% of reference applications generated by supported agents should pass validation and publish successfully on the first attempt** after the agent has access to the platform documentation.

This is a product hypothesis and should be measured rather than treated as an established fact.

---

# 28. Security Metrics

Security metrics SHOULD include:

- red-team suite pass rate
- confirmed cross-Capsule incidents
- confirmed credential exposure incidents
- unauthorized egress attempts blocked
- capability escalation events
- suspension response time

Acceptance target:

> Required security red-team suite passes 100% before release.

Operational target:

> Zero confirmed cross-Capsule data-access incidents.

---

# 29. Scale Envelope

The initial application contract MUST define a supported operating envelope.

The exact numerical values are implementation decisions, but the product MUST specify limits for:

- users per Capsule
- concurrent requests
- SQLite size
- file storage
- request duration
- request rate
- memory
- CPU
- egress bytes
- AI budget

Applications approaching the envelope SHOULD receive warnings.

Applications exceeding the envelope SHOULD follow:

```text
Warn
  ↓
Throttle
  ↓
Export / Graduate / Upgrade
```

The platform MUST NOT silently fail or corrupt data when an application exceeds its supported envelope.

---

# 30. Governance

Every Capsule MUST have:

- owner
- lifecycle state
- creation timestamp
- last activity
- current version
- capability list
- policy status

Governance MUST support:

- suspension
- ownership/deprovisioning handling
- connector revocation
- publish-token revocation
- audit
- inventory
- export
- deletion

The metric for orphaned applications SHOULD be:

> Orphaned applications are detected and actioned within a defined number of days.

Not:

> Orphaned applications = 0.

---

# 31. Risks

| Risk                        | Mitigation                                          |
| --------------------------- | --------------------------------------------------- |
| Sandbox escape              | Strong isolation + adversarial testing              |
| Cross-Capsule data access   | Filesystem, database and network isolation          |
| Cross-origin session theft  | Dedicated origins + host-isolated cookies           |
| Credential theft            | Credential broker + no raw secrets                  |
| Data exfiltration           | Default-deny egress + proxy                         |
| SSRF                        | Trusted DNS/destination validation                  |
| Agent capability escalation | Human approval for capability changes               |
| Resource abuse              | CPU/memory/storage/network quotas                   |
| Malicious dependencies      | Isolated build + dependency controls                |
| Application sprawl          | Ownership + inventory + lifecycle controls          |
| Rollback data loss          | Code-only default + recovery snapshot               |
| Publish failures            | Blessed shape + emulator + validation               |
| High cold-start latency     | Small runtime + sandbox spike                       |
| Infrastructure complexity   | Constrained application contract                    |
| Connector misuse            | Viewer identity default + explicit service identity |
| Unmanaged applications      | Ownership and deprovisioning policy                 |

---

# 32. Technical Decision Register

| Decision                          | Owner                | Due                           |
| --------------------------------- | -------------------- | ----------------------------- |
| Sandbox: Firecracker vs gVisor    | Engineering/Security | Before Phase 0 implementation |
| Exact application domain strategy | Security/Platform    | Before Alpha                  |
| Initial SQLite limits             | Engineering          | Before Alpha                  |
| RPO/RTO targets                   | Product/Engineering  | Before production             |
| AI providers/models               | Product/Security     | Before AI capability          |
| Connector identity model          | Product/Security     | Before connector launch       |
| Enterprise identity provider      | Platform             | Before Phase 2                |
| Scheduled execution model         | Engineering          | Before Phase 3                |

### Sandbox Spike Evaluation

The sandbox spike MUST evaluate:

- isolation strength
- cold-start latency
- network-policy hooks
- filesystem controls
- operational complexity
- idle cost
- debugging experience

---

# 33. Assumptions

1. External AI agents will remain the primary application-building interface.
2. Agents can reliably build against a constrained application shape.
3. Most small applications can operate within SQLite's supported envelope.
4. Most applications do not require unrestricted outbound networking.
5. Platform-managed identity is preferable to application-managed identity for the target use case.
6. Viewer-identity connector access is appropriate as the default where supported.
7. Strong sandboxing is economically feasible for small applications.
8. Users value simple sharing and deployment enough to adopt a constrained runtime.

---

# 34. Dependencies

- identity provider
- object storage
- sandbox runtime
- metadata database
- egress proxy
- credential storage/broker
- DNS/domain infrastructure
- logging infrastructure
- supported external connectors
- Node.js/TypeScript runtime
- platform SDK

---

# 35. Open Questions

1. Firecracker or gVisor for the initial runtime?
2. What exact domain architecture provides the required origin and cookie isolation?
3. What are the initial SQLite size and concurrency limits?
4. What is the exact Alpha RPO/RTO?
5. Which AI providers are supported initially?
6. Which connector launches first?
7. Which identity provider is used for Phase 2 enterprise SSO?
8. What numerical scale envelope should the first production release guarantee?
9. Which scheduled execution model will be used later?
10. What is the exact Capsule export format?

---

# 36. Traceability

Every requirement MUST map to:

```text
Requirement
    ↓
Release / Phase
    ↓
Acceptance Criteria
    ↓
Automated or Manual Test
    ↓
Release Gate
```

Security-critical requirements MUST have automated tests wherever technically feasible.

---

# 37. Definition of Done — Alpha

The following checklist is intentionally **not pre-completed**.

- [ ] Agent can authenticate without a pasted long-lived secret.
- [ ] Agent can run `capsule dev`.
- [ ] Agent can run `capsule validate`.
- [ ] Agent can perform a dry-run publish.
- [ ] Agent can publish a reference application.
- [ ] Application uses the blessed runtime shape.
- [ ] Application runs inside the selected strong sandbox.
- [ ] Capsule has an isolated origin.
- [ ] Authentication works through Google/OIDC.
- [ ] Sharing works for organization users/groups.
- [ ] Capsule has isolated SQLite storage.
- [ ] Resource limits are enforced.
- [ ] Failed deployment does not replace the active version.
- [ ] Machine-readable errors are returned.
- [ ] Agent documentation is available.
- [ ] Basic request/runtime logs are available.

---

# 38. Definition of Done — MVP

- [ ] Capability declaration works.
- [ ] Capability enforcement works outside SDK cooperation.
- [ ] Capability escalation requires human approval.
- [ ] Default-deny egress works.
- [ ] Egress allowlists work.
- [ ] SSRF protections pass security tests.
- [ ] Credential broker works.
- [ ] Viewer identity works where supported.
- [ ] Service identity requires explicit approval.
- [ ] Application roles work.
- [ ] Platform roles work.
- [ ] Every deployment creates a snapshot.
- [ ] Version history works.
- [ ] Code-only rollback works.
- [ ] Data restore requires confirmation.
- [ ] Pre-rollback recovery snapshot is created.
- [ ] Kill switch works.
- [ ] Connector revocation works.
- [ ] Publish-token revocation works.
- [ ] Resource quotas work.
- [ ] Encryption is enabled.
- [ ] Application/data export works.
- [ ] Security red-team suite passes required tests.

---

# 39. Product North Star

The platform succeeds when a person can ask an existing AI agent for a small piece of software and receive a secure, shareable, maintainable application without becoming a cloud infrastructure operator.

The core loop is:

```text
Describe
   ↓
Agent Builds
   ↓
Validate
   ↓
Publish
   ↓
Secure Capsule
   ↓
Share
   ↓
Use
   ↓
Update
   ↓
Approve New Capabilities When Needed
   ↓
Version / Roll Back / Export
```

The product's primary differentiation is **secure execution and operational simplicity for agent-built small software**, not AI code generation.
