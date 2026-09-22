# Environment Profile Specification (capsule/v1alpha1)

This document defines the formal, versioned schema and operational behavior for **Environment Profiles** in the Software Capsule Platform, fulfilling PRD requirements **FR-027 (Environment Profiles)**, **FR-028 (Policy Validation)**, and **FR-032 (Conditional Capability Approval)**.

---

## 1. Overview

An **Environment Profile** defines an organization's security, compliance, and resource policy ceiling. 

### Key Principles
1. **Policy Ceiling**: An application manifest may **narrow** organization policy, but can **never widen** it. Any attempt to request capabilities, runtimes, quotas, or network egress outside the profile ceiling is rejected with structured errors.
2. **Effective Policy**: The platform dynamically computes the intersection between the organization's Environment Profile and the application's declared manifest (GET /apps/{id}/effective-policy).
3. **Conditional Approval (FR-032)**: Deployments that stay within small personal thresholds deploy automatically. Deployments exceeding audience thresholds or introducing sensitive capabilities are held for human owner/admin approval.
4. **Re-Evaluation & Grace Periods**: When an administrator updates the organization's profile, existing capsules are automatically re-evaluated. Non-compliant apps enter a configurable grace period before restriction or suspension.

---

## 2. Schema Specification

The Environment Profile is versioned (ersion: "capsule/v1alpha1") and stored in PostgreSQL (organizations.environment_profile).

`yaml
version: "capsule/v1alpha1"

# 1. Allowed Application Shapes
allowed_shapes:
  - "web-app"

# 2. Allowed Execution Runtimes
allowed_runtimes:
  - "node22"

# 3. Capabilities & Connectors Policy
capabilities:
  allowed_capabilities:
    - "db"
    - "files"
    - "identity"
    - "connectors"
    - "ai"
  connectors:
    # Explicit connector allowlist (use ["*"] to allow all non-disabled)
    allowed_connectors:
      - "slack.post"
      - "sheets.read"
      - "google_sheets.read"
      - "fake.echo"
    # Explicit connector denylist
    disabled_connectors: []
    # Global toggle for service identity
    allow_service_identity: true
    # Per-connector identity permissions: restricts identity modes per connector
    connector_identity_rules:
      slack.post:
        allowed_identities: ["viewer", "service"]
      sheets.read:
        allowed_identities: ["viewer"]
      google_sheets.read:
        allowed_identities: ["viewer"]
      fake.echo:
        allowed_identities: ["viewer", "service"]

# 4. Egress Network Ceiling
egress:
  # Permitted egress destination patterns (FQDNs). ["*"] allows all non-denied FQDNs.
  allowed_domains:
    - "*.slack.com"
    - "*.googleapis.com"
    - "*.github.com"
    - "127.0.0.1" # For local testing/connectors
  # Explicitly forbidden egress destinations (e.g. metadata, private ranges, internal TLDs)
  denied_domains:
    - "169.254.169.254"
    - "*.internal"
    - "*.local"
    - "*.corp"
  # Maximum outbound data transfer allowed per app per day (bytes)
  max_egress_bytes_per_day: 104857600 # 100 MB

# 5. Sharing & Audience Rules
sharing:
  default_scope: "org" # "org" | "user" | "restricted"
  allow_external_sharing: false # Disallow sharing with users outside the organization
  allow_guest_users: false # Disallow unauthenticated or guest viewer access
  max_audience_size: 100 # Maximum number of users an app may be shared with

# 6. AI Gateway Policy
ai:
  allowed_models:
    - "gemini-1.5-flash"
    - "gemini-1.5-pro"
    - "claude-3-5-sonnet"
    - "gpt-4o-mini"
  max_monthly_budget_usd: 50.0

# 7. Resource & Quota Ceilings
quotas:
  max_memory_mb: 512
  max_request_timeout_s: 60
  max_db_size_mb: 100
  max_blob_storage_mb: 500
  apps_per_user: 20
  request_body_max_mb: 10

# 8. Conditional Approval Thresholds (FR-032)
approvals:
  # Apps with audience size <= this threshold that use only standard capabilities deploy automatically
  audience_size_threshold: 5
  # Always require owner approval if service identity is requested
  require_approval_for_service_identity: true
  # Capabilities that require human approval when introduced or widened
  sensitive_capabilities:
    - "connectors"
    - "ai"
    - "files"
  # Require approval when introducing a new outbound network host
  require_approval_for_new_egress: true
  # Require approval if an app is shared organization-wide
  require_approval_for_org_wide_sharing: true

# 9. Expiry & Lifecycle Defaults
expiry:
  default_share_ttl_days: 90
  inactivity_warning_days: 60
  inactivity_suspend_days: 90

# 10. Minimum Security Requirements
security:
  enforce_default_deny_egress: true
  allow_custom_env_vars: false
  prohibit_raw_sockets: true
  require_signed_identity_header: true

# 11. Compliance & Re-Evaluation Policy
compliance:
  grace_period_hours: 72 # 3 days to adjust before restriction/suspension
  enforcement_action: "restrict" # "restrict" | "suspend" | "warn"
`

---

## 3. Structured Policy Errors

When an application manifest attempts to widen a policy beyond the Environment Profile, validation fails closed with a standardized JSON error envelope:

`json
{
  "code": "POLICY_VIOLATION",
  "error": "connector_not_allowed",
  "field": "capabilities.connectors.0.name",
  "rule": "allowed_connectors",
  "message": "Connector 'stripe.charge' is not permitted by organization environment profile.",
  "hint": "Use one of the allowed connectors: ['slack.post', 'google_sheets.read', 'fake.echo'] or contact your organization administrator."
}
`

### Standard Error Codes
| Code | Error Name | Field | Description |
| :--- | :--- | :--- | :--- |
| POLICY_VIOLATION | shape_not_allowed | shape | Requested app shape is not in llowed_shapes. |
| POLICY_VIOLATION | untime_not_allowed | untime | Requested runtime is not in llowed_runtimes. |
| POLICY_VIOLATION | capability_not_allowed | capabilities.<key> | Capability type is disabled by organization. |
| POLICY_VIOLATION | connector_not_allowed | capabilities.connectors.<name> | Connector not permitted by allowlist or in denylist. |
| POLICY_VIOLATION | service_identity_prohibited| capabilities.connectors.<name>.identity | Service identity disabled globally or for connector. |
| POLICY_VIOLATION | egress_domain_denied | egress.<host> | Host matches denylist or is not in allowlist ceiling. |
| POLICY_VIOLATION | external_sharing_prohibited| sharing.allow_external | Manifest or share attempts external/guest sharing. |
| POLICY_VIOLATION | quota_ceiling_exceeded | limits.<resource> | Limit requested in manifest exceeds profile max. |
| POLICY_VIOLATION | i_model_not_allowed | capabilities.ai.model | Model is not in llowed_models. |

---

## 4. Conditional Approval Lifecycle (FR-032)

### Automatic Deployment (Fast Path)
A capsule deployment is approved and activated immediately without human intervention if ALL of the following criteria are met:
1. **Audience Size**: The app is personal or small-team (shared with <= udience_size_threshold users, and default sharing is not "org").
2. **No Service Identity**: All declared connectors use identity: viewer.
3. **No Newly Introduced Sensitive Capabilities**: The update does not add sensitive capabilities (connectors, i) not already present in the currently active version.
4. **Compliant with Profile**: All limits and declarations are within the organization ceiling.

### Human Approval Required (Hold in alidated)
A deployment is held in alidated status and generates pending CapabilityApproval records if ANY of the following occur:
1. Audience size exceeds udience_size_threshold (or default sharing is "org").
2. Service identity is requested on any connector.
3. A new connector or sensitive capability is declared.
4. Outbound egress to a new external domain is requested.

> [!CAUTION]
> **Self-Approval Prohibition**: An AI agent's scoped publish token (	oken_type == "publish_token") can **never** approve capability escalations or conditional approvals. Approvals must be performed by a human organization administrator (owner or editor) using an authenticated user session.

---

## 5. Policy Re-Evaluation Workflow

When an administrator updates the organization's Environment Profile via PUT /v1/organizations/{id}/environment-profile:
1. **Diff Computation**: The platform computes the delta between the old and new profile (added rules, removed rules, tightened limits).
2. **App Scanning**: Every published application in the organization is evaluated against the new ceiling.
3. **Non-Compliance Handling**:
   - Apps with violations are tagged with compliance_status: "non_compliant".
   - The platform calculates grace_period_expires_at = now + grace_period_hours.
   - If grace_period_hours == 0 or upon grace period expiry, the platform applies enforcement_action (e.g. status = "suspended" or compliance_restricted = true).
4. **Audit & Notification**:
   - Generates an immutable audit event: organization.environment_profile_updated.
   - Generates compliance audit events: pp.compliance_warning and pp.compliance_enforced.
