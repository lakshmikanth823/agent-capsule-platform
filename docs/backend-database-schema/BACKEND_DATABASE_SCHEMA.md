# Backend Database Schema

**Version:** `v0.1`  
**Target database:** PostgreSQL 16+  
**Purpose:** Software Capsule control-plane metadata

## Scope

The schema stores:

- Users
- Organizations
- Organization membership and platform roles
- Apps / Software Capsules
- App sharing and application-role assignments
- App versions
- Deployment database snapshot references
- Audit events
- Capability approval records

## Important boundary

This is the **control-plane database**.

Application runtime data is intentionally not stored here. Each Software Capsule uses its own SQLite database in the data plane, with snapshot references recorded in `app_versions.db_snapshot_ref`.

## Core relationships

```text
organizations
    |
    +---- organization_members ---- users
    |
    +---- apps -------------------- users (owner)
             |
             +---- app_versions
             |
             +---- app_shares ------ users
             |
             +---- app_share_policies
             |
             +---- capability_approvals
             |
             +---- audit_events

users ----------------------------- audit_events
organizations --------------------- audit_events
```

## Main tables

### `organizations`

Organization tenant boundary.

Important fields:

- `id`
- `slug`
- `name`
- `status`
- `environment_profile`

### `users`

Normalized identity record.

The `(identity_issuer, identity_subject)` pair is unique so the same external identity cannot create duplicate platform users.

### `organization_members`

Maps users to organizations and assigns platform roles:

- `owner`
- `editor`
- `user`

These are platform roles and are distinct from application roles.

### `apps`

Represents a Software Capsule.

Important fields:

- stable `app_key`
- organization
- owner
- runtime / shape
- status
- current version
- accepted manifest

### `app_versions`

Immutable deployment/version metadata.

Every deployment records:

- version number
- artifact references
- manifest
- publisher
- change description
- database snapshot reference

The database snapshot reference is mandatory because the TRD requires a snapshot on every deployment.

### `app_shares`

User-level access grants and application-role assignments.

Examples:

```text
employee
manager
hr
```

Platform management roles are not stored here.

### `app_share_policies`

Stores application sharing defaults, including the current organization-wide default.

External/guest users are disabled by default.

### `audit_events`

Append-oriented security/governance event record.

An event can identify:

- acting human user
- agent
- tool
- organization
- app
- action
- outcome
- target
- IP address
- user agent
- metadata
- timestamp

This supports the TRD requirement to capture both the human actor and the agent/tool where applicable.

### `capability_approvals`

Tracks human approval for capability escalation.

Examples:

- New connector
- Broadened egress
- AI capability
- Identity capability
- `viewer` -> `service` connector identity

An agent cannot approve its own escalation.

## Security notes

1. Application data is isolated from control-plane metadata.
2. Foreign keys prevent dangling ownership/share/version records where deletion semantics require retention.
3. Audit records preserve actor information independently from the runtime.
4. Capability approval is a separate auditable record.
5. The application manifest remains JSONB so the platform can preserve the exact accepted declaration while schema validation happens at the API boundary.
6. Organization policy is represented as JSONB initially; its final normalized structure can be introduced when Environment Profile requirements stabilize.
7. Audit retention and tamper-resistant storage are deployment-level controls and are not fully enforced by this relational schema alone.
8. Production deployments should restrict direct application access to the control-plane database and use service-specific database roles.

## Suggested service ownership

| Table | Primary service |
|---|---|
| `users` | Identity service |
| `organizations` | Organization service |
| `organization_members` | Access service |
| `apps` | Capsule registry |
| `app_versions` | Version/deployment service |
| `app_shares` | Sharing/access service |
| `app_share_policies` | Sharing/policy service |
| `capability_approvals` | Policy/approval service |
| `audit_events` | Audit/governance service |

## Initial implementation choice

PostgreSQL is the proposed control-plane metadata store. SQLite remains the per-Capsule application database.

Redis, Kubernetes-specific state, marketplace state, and advanced analytics are intentionally absent from this initial schema.
