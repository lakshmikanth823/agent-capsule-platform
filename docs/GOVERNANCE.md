# Software Capsule Platform: Governance, Lifecycle & Inventory Architecture (FR-033 to FR-036)

## Overview

The Software Capsule Platform implements enterprise-grade governance controls governing application ownership, lifecycle expiration, abandoned/orphaned app remediation, and global inventory tracking. These mechanisms satisfy the requirements of **FR-033** (Ownership), **FR-034** (Owner-Left Deprovisioning), **FR-035** (Expiry Lifecycle & Inactivity), and **FR-036** (Application Inventory).

---

## 1. Governance Lifecycle State Machine

Every application exists within a well-defined governance state ensuring an application is **never left without an owner or a pending decision**.

```
                  +----------------------------------------------+
                  |                    normal                    |
                  |     (Healthy, active owner assigned)         |
                  +----------------------------------------------+
                         |                                 |
           Owner Deprovisioned               Inactivity / Expiry Limit
           (No Nominated Owner)                     Reached
                         |                                 |
                         v                                 v
                  +----------------------+                 |
                  |    pending_owner     |                 |
                  | (Grace period active |                 |
                  |  Admins & Editors    |                 |
                  |     notified)        |                 |
                  +----------------------+                 |
                         |                                 |
                 Grace Period Ends                         |
                 (Unassigned)                              |
                         |                                 |
                         v                                 v
                  +----------------------------------------------+
                  |                   archived                   |
                  |  (App suspended, runtime stopped, data kept  |
                  |   during retention window, export offered)   |
                  +----------------------------------------------+
                                         |
                                Retention Window Ends
                                         |
                                         v
                  +----------------------------------------------+
                  |                    purged                    |
                  |  (Database records deleted after export      |
                  |   snapshot offered to organization admins)   |
                  +----------------------------------------------+
```

### State Definitions

| State                  | Status / Description                                                                                                     | Runtime Sandbox State                                       | Operations Allowed                                                     |
| :--------------------- | :----------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------- | :--------------------------------------------------------------------- |
| `normal`               | Application has an active, valid owner in good standing within the organization.                                         | Active (`ready` / `suspended` via idle wake-on-request).    | Full read/write, publishing, sharing, runtime execution.               |
| `pending_owner`        | App owner was deprovisioned (via SCIM or manual removal) without a pre-designated nominee. Grace period timer is active. | Active during grace period to preserve business continuity. | Read, execution, and admin ownership assignment. Publishing locked.    |
| `grace_period_expired` | Grace period ended without an administrator or editor claiming or assigning ownership.                                   | Suspended immediately.                                      | Invocations blocked (HTTP 503 / 403 `APP_SUSPENDED_NO_OWNER`).         |
| `archived`             | Inactivity limit or fixed expiry date reached. Retained for `purge_after_days` (default 30 days).                        | Suspended. SQLite and blobs preserved.                      | Full data export snapshot (`GET /v1/apps/{id}/export-data`) available. |
| `purged`               | Permanent deletion after expiration of the retention window.                                                             | Deleted.                                                    | Tombstone audit records preserved in cryptographic hash chain.         |

---

## 2. Ownership & Ownership Transfer (FR-033)

### Permissions & Policy

- **Authorized Callers**:
  - The current application owner.
  - Organization administrators (`owner` role in `OrganizationMember`).
- **Validation Rules**:
  - The new owner must exist and hold an active membership in the same organization.
  - Attempting to transfer to a user outside the organization is rejected with HTTP 400 (`USER_NOT_IN_ORGANIZATION`).
  - Editors without org-admin privileges cannot transfer ownership (HTTP 403 `PERMISSION_DENIED`).
- **Audit & Notifications**:
  - Dispatches `app.ownership_transferred` structured audit event into the SHA-256 hash chain with metadata containing `previous_owner_id`, `new_owner_id`, and `transferred_by`.
  - Sends immediate notification via `NotificationSender` to both the previous owner and the new owner.

### Nominated Owner Setup

Application owners can nominate a successor at any time via `PATCH /v1/apps/{id}/governance` or `capsule set-governance --nominated-owner <user-id>`. When an owner leaves, pre-nominated successors are automatically promoted without triggering grace period interruptions.

---

## 3. Owner-Left Handling & SCIM Integration (FR-034)

When an employee departs the organization (either through an automated **SCIM 2.0 deprovisioning cascade** or manual administrator removal via `DELETE /v1/organizations/{org_id}/members/{user_id}`), `deprovisioning.py` invokes `GovernanceService.handle_owner_left(...)`:

```
User Deprovisioned
       |
       +---> Revoke Active Sessions & Publish Tokens
       +---> Revoke Connector OAuth Tokens
       +---> Query All Apps Owned by User
       |
       +---> For Each App:
                |
                +-- Nominated Owner Present?
                |       |
                |       +-- YES: Auto-transfer ownership immediately
                |       |        Send notification & record audit event
                |       |
                |       +-- NO: Start Grace Period (default: 14 days)
                |               Set governance_state = "pending_owner"
                |               Set governance_deadline = now + grace_period
                |               Notify Org Admins and App Editors
                |               App remains active until deadline
```

### Configurable Grace Period

Organizations configure the default grace period in their `Organization.environment_profile`:

```json
{
  "governance": {
    "owner_left_policy": "grace_period",
    "owner_left_grace_period_days": 14,
    "default_inactivity_days_limit": 90,
    "default_expiry_days": 365,
    "warning_intervals_days": [14, 7, 1],
    "purge_after_days": 30
  }
}
```

---

## 4. Expiry Lifecycle & Inactivity Tracking (FR-035)

### Inactivity Tracking

- Every app tracks `last_activity_at` (timestamp).
- Updated automatically on application HTTP traffic via Edge Proxy or explicitly via `POST /v1/apps/{id}/activity`.
- If `now - last_activity_at > inactivity_days_limit`, the application is flagged for expiration.

### Warning Cadence

Before any capsule is archived or deleted, automated warnings are sent at configurable intervals (defaults: **14 days**, **7 days**, and **1 day** prior to the deadline):

- Warnings record an immutable audit event `app.governance_warning` recording days remaining.
- Notifications are dispatched to the application owner, nominated owner, and org admins.
- Tracking array `governance_warnings_sent` prevents duplicate warnings for the same interval.

### Archival & Data Export

1. Upon reaching the deadline, the app is transitioned to `archived` (`governance_state = "archived"` and `status = "suspended"`).
2. All sandbox runtime processes are stopped.
3. Database (`app.sqlite`), blob storage, and manifest configuration are preserved.
4. Administrators can download the full archive bundle at `GET /v1/apps/{id}/export-data` containing:
   - Application metadata and governance records.
   - Latest manifest and version history.
   - Active user shares and role mappings.
   - SHA-256 database snapshot reference.
5. After `purge_after_days` expires, the background job permanently purges the capsule records while preserving the audit hash chain.

---

## 5. Application Inventory (FR-036)

The platform provides comprehensive inventory discovery across all organizational capsules.

### Inventory API

`GET /v1/organizations/{org_id}/inventory`

**Response Structure**:

```json
{
  "items": [
    {
      "id": "app_12345",
      "name": "Leave Tracker",
      "status": "ready",
      "governance_state": "normal",
      "owner_id": "usr_alice",
      "owner_email": "alice@acme.com",
      "owner_name": "Alice Smith",
      "nominated_owner_id": "usr_bob",
      "nominated_owner_email": "bob@acme.com",
      "user_count": 42,
      "capabilities": ["db", "identity", "connectors"],
      "connectors": ["sheets.read"],
      "current_version": 3,
      "last_activity_at": "2026-09-21T14:32:00Z",
      "expires_at": "2027-09-21T00:00:00Z",
      "inactivity_days_limit": 90,
      "governance_deadline": null,
      "created_at": "2026-01-15T09:00:00Z"
    }
  ],
  "total": 1,
  "stats": {
    "total_apps": 1,
    "active_apps": 1,
    "pending_owner_apps": 0,
    "archived_apps": 0,
    "expiring_soon_apps": 0
  }
}
```

### Streaming RFC 4180 CSV Export

`GET /v1/organizations/{org_id}/inventory/export?format=csv`
Streams compliant CSV with headers:
`id,name,status,governance_state,owner_id,owner_email,nominated_owner_email,current_version,user_count,capabilities,connectors,last_activity_at,expires_at,governance_deadline,created_at`

### Dashboard Inventory Screen

Implemented in `apps/dashboard/src/screens/InventoryScreen.tsx`:

- **KPI Summary Cards**: Total Apps, Active Apps, Pending Owner, Archived, Expiring Soon.
- **Search & Filters**: Real-time filtering by status, governance state, search keywords (ID, name, owner email).
- **Interactive Ownership Transfer**: Modal dialog to reassign ownership with instant validation.
- **Direct Export**: One-click download of CSV and JSON reports.

---

## 6. Scheduled Governance Background Worker

The background worker executes periodically (or on-demand via `POST /v1/organizations/{org_id}/governance/run-cycle`):

1. **Detect Orphaned / Unowned Apps**: Flags any capsule missing an active owner and transitions it into `pending_owner`.
2. **Evaluate Grace Periods**: Suspends applications whose `governance_deadline` has passed without ownership resolution.
3. **Evaluate Inactivity & Expiry**: Compares `last_activity_at` and `expires_at` against configured policies.
4. **Issue Advance Warnings**: Dispatches notifications and audit events at 14d, 7d, and 1d thresholds.
5. **Archive & Purge**: Transitions expired apps to `archived` and cleans up purged apps beyond retention limits.

---

## 7. CLI Commands

The Capsule CLI provides administrative and developer tools for governance:

```bash
# List organization inventory with tabular display
capsule inventory --org <org-id>

# Export inventory to CSV or JSON
capsule inventory --org <org-id> --export csv > inventory.csv
capsule inventory --org <org-id> --export json > inventory.json

# Transfer ownership of an application
capsule transfer-ownership <app-id> --new-owner <user-id>

# Configure governance parameters and nominee
capsule set-governance <app-id> \
  --nominated-owner <user-id> \
  --expires-at 2027-01-01T00:00:00Z \
  --inactivity-days 60
```

---

## 8. Verification & Test Evidence

| Test Suite             | Scenario                                                   | Validated Behavior                                                                           |
| :--------------------- | :--------------------------------------------------------- | :------------------------------------------------------------------------------------------- |
| `test_governance.py`   | `test_ownership_transfer_by_owner_and_admin`               | Owner or org admin can transfer ownership; audit event and notifications sent.               |
| `test_governance.py`   | `test_ownership_transfer_forbidden_for_non_admin_editor`   | Non-admin editors rejected with 403 Forbidden.                                               |
| `test_governance.py`   | `test_owner_left_with_nominated_owner_auto_transfers`      | SCIM/deprovisioning immediately assigns nominated owner without grace period.                |
| `test_governance.py`   | `test_owner_left_without_nominee_enters_grace_period`      | Enters `pending_owner` state, sets 14-day deadline, broadcasts alerts to editors and admins. |
| `test_governance.py`   | `test_governance_cycle_suspends_when_grace_period_expires` | Lifecycle worker transitions expired grace period to suspended `grace_period_expired`.       |
| `test_governance.py`   | `test_expiry_warnings_dispatched_at_intervals`             | Evaluates 14d, 7d, 1d warning thresholds without duplicate dispatches.                       |
| `test_governance.py`   | `test_inactivity_based_expiry_and_archival`                | Inactive applications transitioned to `archived` and status suspended.                       |
| `test_governance.py`   | `test_purged_app_data_export_snapshot`                     | Verified full data export bundle available before database purge.                            |
| `test_sso_and_scim.py` | `test_scim_deprovisioning_cascade_and_owner_left_hook`     | End-to-end SCIM DELETE cascades into owner-left governance handler.                          |
| `inventory.test.ts`    | CLI inventory tests                                        | Validates table formatting, JSON exports, and ownership transfer command.                    |
