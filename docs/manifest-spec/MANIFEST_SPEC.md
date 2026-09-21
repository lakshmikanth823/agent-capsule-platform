# Software Capsule Manifest Specification

**Version:** `v1alpha1`  
**Artifact:** Software Capsule app description file  
**Schema:** `capsule.manifest.schema.json`

## 1. Purpose

The Software Capsule Manifest is the declarative description of an agent-published application. It declares the application shape, runtime, application roles, requested capabilities, network destinations, sharing policy, schedules, and resource limits.

The manifest is an input to platform validation and policy enforcement. A valid JSON Schema document does **not** by itself grant a capability. Organization policy and the platform security baseline can impose stricter rules.

## 2. Canonical file

The canonical human-editable format is YAML:

`capsule.manifest.yaml`

The same document can be represented as JSON and validated against:

`capsule.manifest.schema.json`

## 3. Top-level fields

| Field | Required | Meaning |
|---|---|---|
| `apiVersion` | Yes | Manifest contract version. `capsule/v1alpha1`. |
| `id` | Yes | Stable Capsule identifier. |
| `name` | Yes | Human-readable application name. |
| `shape` | Yes | Blessed application shape. Alpha/MVP uses `web-app`. |
| `runtime` | Yes | Blessed runtime. Alpha/MVP uses `node22`. |
| `roles` | No | Application roles such as `employee`, `manager`, `hr`. |
| `capabilities` | No | Requested platform capabilities. |
| `egress` | No | Explicit network destinations. Empty means default-deny egress. |
| `schedule` | No | Scheduled handlers. Scheduled execution is deferred in the roadmap until Phase 3. |
| `sharing` | No | Default sharing policy. |
| `limits` | No | Requested resource limits; platform/org policy may impose lower limits. |

## 4. Capability model

### Database

```yaml
capabilities:
  db:
    type: sqlite
```

SQLite is the default Capsule database. The initial runtime assumes a single active instance for writes.

PostgreSQL is not part of the initial manifest contract; it is a later capability.

### Identity

```yaml
capabilities:
  identity: true
```

Requests application identity context from the platform. The application receives verified identity information through the platform identity mechanism rather than managing the organization's primary login itself.

### Files

```yaml
capabilities:
  files:
    max_mb: 200
```

Requests Capsule file/blob storage up to the declared limit.

### AI

```yaml
capabilities:
  ai:
    monthly_budget_usd: 5
```

Requests AI access with a declared monthly budget. Model/provider allowlists, payer configuration, and logging/retention policy are controlled outside the manifest by platform/organization policy.

### Connectors

```yaml
capabilities:
  connectors:
    - name: sheets.read
      acts_as: viewer
```

Connector access is capability-based. `viewer` is the default identity model.

```yaml
capabilities:
  connectors:
    - name: slack.post
      channel: "#hr-leave"
      acts_as: service
```

`service` identity is a privileged capability and requires explicit approval/configuration. Applications never receive raw connector credentials.

## 5. Network egress

```yaml
egress: []
```

An empty list represents default-deny egress.

If destinations are declared, the platform still applies the organization policy and security baseline. The manifest cannot weaken network protections, including private-address, metadata-service, loopback, IPv4/IPv6, redirect, and DNS-rebinding protections.

## 6. Application roles

```yaml
roles:
  - employee
  - manager
  - hr
```

These are **application roles**, not platform management roles.

Platform roles are separately defined by the platform:

- Owner
- Editor
- User

Application roles control behavior inside the Capsule. Platform roles control who can manage the Capsule and its sharing/capability configuration.

## 7. Sharing

```yaml
sharing:
  default: org
```

The current contract represents organization sharing. External/guest sharing is not enabled by default in the Alpha scope.

Actual access is still subject to identity verification, organization policy, and per-application assignments.

## 8. Resource limits

Example:

```yaml
limits:
  cpu: small
  memory_mb: 256
  request_timeout_s: 30
  db_max_mb: 500
  blob_max_mb: 200
  max_active_instances: 1
```

The manifest declares requested limits. The platform may enforce stricter ceilings.

`max_active_instances: 1` reflects the initial SQLite write model.

## 9. Scheduling

The manifest can represent a scheduled handler:

```yaml
schedule:
  - cron: "0 9 * * MON"
    handler: weekly_digest
```

Scheduled execution is represented for forward compatibility, but the current roadmap defers production scheduling to Phase 3. Alpha/MVP deployment validation should reject or explicitly defer this capability rather than silently activating it.

## 10. Validation layers

Manifest validation is not a single check. The expected sequence is:

1. **Syntax validation** — YAML/JSON parses successfully.
2. **Schema validation** — document conforms to the JSON Schema.
3. **Semantic validation** — names, references, handlers, limits, and combinations are valid.
4. **Security validation** — requested capabilities and network destinations pass platform security rules.
5. **Environment Profile validation** — organization policy allows the requested configuration.
6. **Approval validation** — new or broadened capabilities, service identity, or restricted connectors have required human approval.
7. **Deployment admission** — only then can the Capsule proceed to build/deploy.

The manifest can narrow an Environment Profile, but cannot widen it.

## 11. Capability escalation

A deployment that introduces a new or broadened capability is blocked until the human owner approves it.

Examples:

- adding `identity: true`
- adding AI access
- adding a new connector
- changing a connector from `viewer` to `service`
- broadening network egress

An agent or publish credential cannot approve its own escalation.

## 12. Versioning

Every successful deployment creates an immutable Capsule version. A database snapshot is taken with every deployment.

Rollback behavior is:

- code-only rollback when schema compatibility is established;
- explicit code + data restore when required, with a visible data-loss warning;
- a fresh recovery snapshot is created immediately before any rollback.

## 13. Security invariants

The manifest must never be treated as a trust boundary. Generated application code is untrusted.

The platform must enforce security independently of application cooperation, including:

- strong sandbox isolation;
- non-root execution;
- CPU/memory/time limits;
- filesystem isolation;
- default-deny network egress;
- SSRF protections;
- cross-Capsule isolation;
- origin/session isolation;
- credential brokering;
- scoped and revocable publish credentials;
- organization policy;
- audit logging;
- owner/admin/platform kill switch.

## 14. Example minimal manifest

```yaml
apiVersion: capsule/v1alpha1

id: team-dashboard
name: team-dashboard
shape: web-app
runtime: node22

capabilities:
  db:
    type: sqlite
  identity: true

egress: []

sharing:
  default: org

limits:
  cpu: small
  memory_mb: 256
  request_timeout_s: 30
  max_active_instances: 1
```

## 15. Example connector-enabled manifest

```yaml
apiVersion: capsule/v1alpha1

id: leave-tracker
name: leave-tracker
shape: web-app
runtime: node22

roles:
  - employee
  - manager
  - hr

capabilities:
  db:
    type: sqlite
  identity: true
  files:
    max_mb: 200
  ai:
    monthly_budget_usd: 5
  connectors:
    - name: slack.post
      channel: "#hr-leave"
      acts_as: service
    - name: sheets.read
      acts_as: viewer

egress: []

sharing:
  default: org

limits:
  cpu: small
  memory_mb: 256
  request_timeout_s: 30
  db_max_mb: 500
  blob_max_mb: 200
  max_active_instances: 1
```

## 16. Implementation note

This manifest contract is intentionally narrow. The initial blessed shape is a single Node.js/TypeScript web application using the platform SDK. Additional runtimes, application shapes, PostgreSQL-per-Capsule, arbitrary containers, and scheduled execution are later-phase capabilities rather than Alpha requirements.

The JSON Schema defines the document shape; platform policy, Environment Profiles, capability approval, and runtime enforcement remain authoritative.
