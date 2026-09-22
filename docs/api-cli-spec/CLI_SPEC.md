# Software Capsule CLI Specification

**Version:** `v0.1`  
**CLI:** `capsule`

The CLI is the primary agent-facing interface together with the REST API. MCP is a thin adapter over the same API operations.

## 1. Authentication

```bash
capsule login
```

The CLI should use OAuth/device-code or an equivalent browser-based flow. It must not require users or agents to paste long-lived secrets into terminal arguments.

Session credentials are short-lived, scoped, and revocable.

## 2. Initialize

```bash
capsule init
```

Creates a starter `capsule.manifest.yaml` and local project configuration.

## 3. Validate

```bash
capsule validate
```

Validates:

1. YAML/JSON syntax
2. JSON Schema
3. semantic constraints
4. capability combinations
5. environment-policy compatibility where available

Machine-readable form:

```bash
capsule validate --json
```

Expected exit codes:

| Code | Meaning                            |
| ---: | ---------------------------------- |
|  `0` | Valid                              |
|  `2` | Manifest/schema error              |
|  `3` | Policy violation                   |
|  `4` | Approval required                  |
|  `5` | Authentication/authorization error |
| `10` | Platform/network error             |

## 4. Local development

```bash
capsule dev
```

Starts the local emulator for the blessed application shape.

The emulator provides compatible interfaces for:

- SQLite
- identity context
- files/blob SDK
- selected capability APIs

Local development must not expose production credentials.

## 5. Dry run

```bash
capsule publish --dry-run
```

Runs validation and admission checks without creating a live deployment.

Example JSON:

```bash
capsule publish --dry-run --json
```

```json
{
  "valid": true,
  "required_approvals": [],
  "warnings": []
}
```

## 6. Publish

```bash
capsule publish
```

Publishes the current project using `capsule.manifest.yaml`.

Useful options:

```bash
capsule publish --description "Add manager leave approval"
capsule publish --wait
capsule publish --json
```

The publish operation is idempotent.

A publish creates an immutable application version after successful validation/build/deployment.

The CLI should show:

```text
Validating manifest... OK
Checking policy... OK
Building artifact... OK
Creating snapshot... OK
Deploying version 7... OK
Live URL: https://leave-tracker.<app-domain>
```

If capability escalation is detected:

```text
Deployment blocked.
Reason: CAPABILITY_APPROVAL_REQUIRED
Capability: connectors.slack.post
Requested identity: service
Approval required from: app owner
```

The agent cannot approve its own escalation.

## 7. Publish with expected version

```bash
capsule publish --expected-version 7
```

If the server's current version differs, the publish fails with a conflict rather than silently overwriting another update.

## 8. Operation status

```bash
capsule status
```

or:

```bash
capsule operation get <operation-id>
```

Example:

```text
Operation: 2f8...
Type: publish
Status: succeeded
Version: 8
```

## 9. Share

Share a Capsule with an organization user and assign an application role:

```bash
capsule share add --user alice@example.com --role manager
```

List shares:

```bash
capsule share list
```

Revoke:

```bash
capsule share revoke <share-id>
```

Optional expiration:

```bash
capsule share add   --user contractor@example.com   --role employee   --expires-at 2026-10-01T00:00:00Z
```

External/guest sharing is disabled by default in Alpha.

Only authorized platform roles can change sharing assignments.

## 10. Rollback

List versions:

```bash
capsule versions
```

Rollback to a previous version:

```bash
capsule rollback --version 6
```

Default mode is code-only when the target version is schema-compatible.

For explicit code + data restore:

```bash
capsule rollback   --version 6   --mode code-and-data   --confirm-data-restore
```

The CLI must display a data-loss warning before the destructive restore.

Example:

```text
WARNING: This operation restores application data from the snapshot
associated with version 6.

Current data created after that snapshot may be lost.

Continue? [y/N]
```

A fresh recovery snapshot is created immediately before rollback.

Rollback itself creates an auditable deployment operation and should be undoable by rolling forward to the recovery version.

## 11. Logs

Recent logs:

```bash
capsule logs
```

Follow logs:

```bash
capsule logs --follow
```

Errors only:

```bash
capsule logs --level error
```

Time range:

```bash
capsule logs   --from 2026-09-21T08:00:00Z   --to 2026-09-21T10:00:00Z
```

JSON output for agents:

```bash
capsule logs --json
```

Sensitive values must be redacted before logs are returned.

## 12. App information

```bash
capsule app get
```

Example:

```text
Name: leave-tracker
Shape: web-app
Runtime: node22
Status: active
Current version: 8
URL: https://leave-tracker.<app-domain>
```

## 13. Version history

```bash
capsule versions
```

Expected output:

```text
VERSION  STATUS      PUBLISHED               PUBLISHER
8        published   2026-09-21 09:42 UTC   Eswar
7        published   2026-09-20 16:18 UTC   agent/codex
6        rolled_back 2026-09-18 12:05 UTC   Eswar
```

## 14. Agent-friendly behavior

Every command that changes state should support:

```bash
--json
```

Errors should include stable machine-readable codes.

Commands should be safe to retry.

Publishing should use an idempotency key generated by the CLI and reused when retrying the same logical operation.

The CLI should avoid requiring interactive prompts when `--json` is supplied. Operations that require destructive confirmation must fail closed unless an explicit confirmation flag is provided.

## 15. Suggested command tree

```text
capsule
├── login
├── init
├── dev
├── validate
├── publish
├── status
├── app
│   └── get
├── versions
├── operation
│   └── get
├── share
│   ├── add
│   ├── list
│   └── revoke
├── rollback
└── logs
```

## 16. API-to-CLI mapping

| CLI                    | API                                          |
| ---------------------- | -------------------------------------------- |
| `capsule app get`      | `GET /apps/{appId}`                          |
| `capsule validate`     | `POST /apps/{appId}/validate`                |
| `capsule publish`      | `POST /apps/{appId}/publish`                 |
| `capsule status`       | `GET /apps/{appId}/operations/{operationId}` |
| `capsule versions`     | `GET /apps/{appId}/versions`                 |
| `capsule rollback`     | `POST /apps/{appId}/rollback`                |
| `capsule share add`    | `POST /apps/{appId}/shares`                  |
| `capsule share list`   | `GET /apps/{appId}/shares`                   |
| `capsule share revoke` | `DELETE /apps/{appId}/shares/{shareId}`      |
| `capsule logs`         | `GET /apps/{appId}/logs`                     |

## 17. API behavior rules

### Authorization

- Owner/Editor can publish subject to policy.
- Owner/Editor can change app sharing assignments.
- User can access an app only when application sharing and role policy permit it.
- Rollback requires the app-management permission and any organization policy approval.
- Logs are restricted to authorized app/platform administrators.

### Idempotency

All state-changing endpoints should accept `Idempotency-Key`.

The server stores the result for a bounded retention period and returns the original result for a retry of the same request.

Reusing a key with materially different request content returns an idempotency conflict.

### Optimistic concurrency

Publish accepts `expected_current_version`.

This prevents an agent from unknowingly publishing against stale state.

### Error model

Stable error codes include:

```text
INVALID_MANIFEST
SCHEMA_VALIDATION_FAILED
POLICY_VIOLATION
CAPABILITY_APPROVAL_REQUIRED
UNAUTHORIZED
FORBIDDEN
APP_NOT_FOUND
VERSION_NOT_FOUND
VERSION_CONFLICT
ROLLBACK_NOT_COMPATIBLE
DATA_RESTORE_CONFIRMATION_REQUIRED
QUOTA_EXCEEDED
BUILD_FAILED
DEPLOYMENT_FAILED
IDEMPOTENCY_CONFLICT
RATE_LIMITED
INTERNAL_ERROR
```

### Audit

The server records audit events for:

- app creation
- publish
- validation failure where security-relevant
- sharing changes
- role changes
- rollback
- capability approval/rejection
- connector access
- kill-switch actions
- ownership changes
- policy changes

Audit records capture the acting user and agent/tool when available.

## 18. API versioning

The proposed API uses:

```text
/v1
```

The manifest has its own independent contract version:

```yaml
apiVersion: capsule/v1alpha1
```

API version and manifest version must not be treated as the same compatibility mechanism.
