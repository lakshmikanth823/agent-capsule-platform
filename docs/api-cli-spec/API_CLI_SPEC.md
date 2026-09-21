# API and CLI Specification

openapi: 3.1.0
info:
  title: Software Capsule Platform API
  version: 0.1.0
  description: |
    Proposed control-plane API for publishing, sharing, inspecting, rolling back,
    and retrieving logs for Software Capsules.
servers:
  - url: https://api.example.invalid/v1
    description: Proposed API base URL

security:
  - bearerAuth: []

tags:
  - name: Apps
  - name: Versions
  - name: Sharing
  - name: Logs
  - name: Validation

paths:
  /apps:
    post:
      tags: [Apps]
      summary: Create an app
      operationId: createApp
      description: Creates a draft Software Capsule registry entry.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateAppRequest'
      responses:
        '201':
          description: App created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/App'
        '400':
          $ref: '#/components/responses/BadRequest'
        '409':
          $ref: '#/components/responses/Conflict'
    get:
      tags: [Apps]
      summary: List apps
      operationId: listApps
      parameters:
        - $ref: '#/components/parameters/Limit'
        - $ref: '#/components/parameters/Cursor'
        - name: status
          in: query
          schema:
            type: string
            enum: [draft, active, suspended, archived]
      responses:
        '200':
          description: App list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AppList'

  /apps/{appId}:
    parameters:
      - $ref: '#/components/parameters/AppId'
    get:
      tags: [Apps]
      summary: Get app
      operationId: getApp
      responses:
        '200':
          description: App
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/App'
        '404':
          $ref: '#/components/responses/NotFound'

  /apps/{appId}/validate:
    post:
      tags: [Validation]
      summary: Validate a manifest without deploying
      operationId: validateApp
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ValidateRequest'
      responses:
        '200':
          description: Validation result
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ValidationResult'
        '400':
          $ref: '#/components/responses/BadRequest'

  /apps/{appId}/publish:
    post:
      tags: [Apps]
      summary: Publish a new app version
      operationId: publishApp
      description: |
        Idempotent publish endpoint. Validates manifest, applies policy,
        checks required approvals, builds the artifact, creates a deployment
        version and returns deployment status.
      parameters:
        - $ref: '#/components/parameters/IdempotencyKey'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/PublishRequest'
      responses:
        '202':
          description: Publish accepted
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/PublishOperation'
        '400':
          $ref: '#/components/responses/BadRequest'
        '403':
          $ref: '#/components/responses/Forbidden'
        '409':
          $ref: '#/components/responses/Conflict'
        '422':
          description: Manifest or policy validation failed
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ValidationResult'

  /apps/{appId}/versions:
    get:
      tags: [Versions]
      summary: List app versions
      operationId: listVersions
      parameters:
        - $ref: '#/components/parameters/AppId'
        - $ref: '#/components/parameters/Limit'
        - $ref: '#/components/parameters/Cursor'
      responses:
        '200':
          description: Version list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/VersionList'

  /apps/{appId}/versions/{versionId}:
    parameters:
      - $ref: '#/components/parameters/AppId'
      - $ref: '#/components/parameters/VersionId'
    get:
      tags: [Versions]
      summary: Get version
      operationId: getVersion
      responses:
        '200':
          description: Version
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AppVersion'
        '404':
          $ref: '#/components/responses/NotFound'

  /apps/{appId}/rollback:
    post:
      tags: [Versions]
      summary: Roll back to a previous version
      operationId: rollbackApp
      description: |
        Creates a new rollback deployment. Code-only rollback is the default
        when schema-compatible. Code+data restore requires explicit confirmation
        and a visible data-loss warning. A fresh recovery snapshot is created
        before the rollback operation.
      parameters:
        - $ref: '#/components/parameters/AppId'
        - $ref: '#/components/parameters/IdempotencyKey'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RollbackRequest'
      responses:
        '202':
          description: Rollback accepted
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RollbackOperation'
        '400':
          $ref: '#/components/responses/BadRequest'
        '403':
          $ref: '#/components/responses/Forbidden'
        '409':
          $ref: '#/components/responses/Conflict'
        '422':
          description: Rollback requires confirmation or is not compatible
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'

  /apps/{appId}/shares:
    get:
      tags: [Sharing]
      summary: List app shares
      operationId: listShares
      parameters:
        - $ref: '#/components/parameters/AppId'
        - $ref: '#/components/parameters/Limit'
        - $ref: '#/components/parameters/Cursor'
      responses:
        '200':
          description: Share list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ShareList'
    post:
      tags: [Sharing]
      summary: Create or assign an app share
      operationId: createShare
      parameters:
        - $ref: '#/components/parameters/AppId'
        - $ref: '#/components/parameters/IdempotencyKey'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateShareRequest'
      responses:
        '201':
          description: Share created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AppShare'
        '403':
          $ref: '#/components/responses/Forbidden'
        '409':
          $ref: '#/components/responses/Conflict'

  /apps/{appId}/shares/{shareId}:
    parameters:
      - $ref: '#/components/parameters/AppId'
      - $ref: '#/components/parameters/ShareId'
    delete:
      tags: [Sharing]
      summary: Revoke an app share
      operationId: revokeShare
      responses:
        '204':
          description: Share revoked
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'

  /apps/{appId}/logs:
    get:
      tags: [Logs]
      summary: Retrieve application logs
      operationId: getLogs
      description: Returns bounded, paginated runtime logs. Sensitive values must be redacted before exposure.
      parameters:
        - $ref: '#/components/parameters/AppId'
        - name: from
          in: query
          schema:
            type: string
            format: date-time
        - name: to
          in: query
          schema:
            type: string
            format: date-time
        - name: level
          in: query
          schema:
            type: string
            enum: [debug, info, warn, error]
        - name: cursor
          in: query
          schema:
            type: string
        - $ref: '#/components/parameters/Limit'
      responses:
        '200':
          description: Logs
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/LogList'
        '403':
          $ref: '#/components/responses/Forbidden'

  /apps/{appId}/operations/{operationId}:
    get:
      tags: [Apps]
      summary: Get publish or rollback operation status
      operationId: getOperation
      parameters:
        - $ref: '#/components/parameters/AppId'
        - name: operationId
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: Operation
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Operation'
        '404':
          $ref: '#/components/responses/NotFound'

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: OAuth2

  parameters:
    AppId:
      name: appId
      in: path
      required: true
      schema:
        type: string
        format: uuid
    VersionId:
      name: versionId
      in: path
      required: true
      schema:
        type: string
        format: uuid
    ShareId:
      name: shareId
      in: path
      required: true
      schema:
        type: string
        format: uuid
    Limit:
      name: limit
      in: query
      schema:
        type: integer
        minimum: 1
        maximum: 100
        default: 50
    Cursor:
      name: cursor
      in: query
      schema:
        type: string
    IdempotencyKey:
      name: Idempotency-Key
      in: header
      required: true
      schema:
        type: string
        minLength: 16
        maxLength: 255

  responses:
    BadRequest:
      description: Invalid request
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
    Forbidden:
      description: Caller is not authorized
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
    NotFound:
      description: Resource not found
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
    Conflict:
      description: State conflict or idempotency conflict
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'

  schemas:
    CreateAppRequest:
      type: object
      required: [id, name, shape, runtime, manifest]
      properties:
        id:
          type: string
          pattern: '^[a-z0-9][a-z0-9-]{0,62}$'
        name:
          type: string
          maxLength: 80
        shape:
          type: string
          const: web-app
        runtime:
          type: string
          const: node22
        manifest:
          type: object

    PublishRequest:
      type: object
      required: [manifest, artifact]
      properties:
        manifest:
          type: object
        artifact:
          type: object
          required: [ref]
          properties:
            ref:
              type: string
            sha256:
              type: string
              pattern: '^[a-fA-F0-9]{64}$'
        change_description:
          type: string
          maxLength: 2000
        expected_current_version:
          type: integer
          minimum: 1

    ValidateRequest:
      type: object
      required: [manifest]
      properties:
        manifest:
          type: object

    RollbackRequest:
      type: object
      required: [target_version_id, mode]
      properties:
        target_version_id:
          type: string
          format: uuid
        mode:
          type: string
          enum: [code_only, code_and_data]
        confirm_data_restore:
          type: boolean
          default: false
        reason:
          type: string
          maxLength: 2000

    CreateShareRequest:
      type: object
      required: [user_id, app_role]
      properties:
        user_id:
          type: string
          format: uuid
        app_role:
          type: string
          pattern: '^[a-z][a-z0-9_-]{0,63}$'
        expires_at:
          type: string
          format: date-time

    App:
      type: object
      required: [id, name, status, shape, runtime, created_at, updated_at]
      properties:
        id:
          type: string
          format: uuid
        organization_id:
          type: string
          format: uuid
        owner_user_id:
          type: string
          format: uuid
        app_key:
          type: string
        name:
          type: string
        status:
          type: string
        shape:
          type: string
        runtime:
          type: string
        current_version_id:
          type: string
          format: uuid
          nullable: true
        app_url:
          type: string
          format: uri
          nullable: true
        created_at:
          type: string
          format: date-time
        updated_at:
          type: string
          format: date-time

    AppVersion:
      type: object
      properties:
        id:
          type: string
          format: uuid
        app_id:
          type: string
          format: uuid
        version_number:
          type: integer
        status:
          type: string
        manifest:
          type: object
        source_artifact_ref:
          type: string
        build_artifact_ref:
          type: string
          nullable: true
        db_snapshot_ref:
          type: string
        publisher_user_id:
          type: string
          format: uuid
          nullable: true
        publisher_agent:
          type: string
          nullable: true
        change_description:
          type: string
          nullable: true
        published_at:
          type: string
          format: date-time
          nullable: true

    AppShare:
      type: object
      properties:
        id:
          type: string
          format: uuid
        app_id:
          type: string
          format: uuid
        user_id:
          type: string
          format: uuid
        app_role:
          type: string
        status:
          type: string
        granted_at:
          type: string
          format: date-time
        expires_at:
          type: string
          format: date-time
          nullable: true

    Operation:
      type: object
      properties:
        operation_id:
          type: string
          format: uuid
        type:
          type: string
          enum: [publish, rollback]
        status:
          type: string
          enum: [queued, running, succeeded, failed, cancelled]
        app_id:
          type: string
          format: uuid
        version_id:
          type: string
          format: uuid
          nullable: true
        errors:
          type: array
          items:
            $ref: '#/components/schemas/Error'
        created_at:
          type: string
          format: date-time
        updated_at:
          type: string
          format: date-time

    PublishOperation:
      allOf:
        - $ref: '#/components/schemas/Operation'

    RollbackOperation:
      allOf:
        - $ref: '#/components/schemas/Operation'

    ValidationResult:
      type: object
      required: [valid, checks]
      properties:
        valid:
          type: boolean
        checks:
          type: array
          items:
            $ref: '#/components/schemas/ValidationCheck'
        required_approvals:
          type: array
          items:
            type: string

    ValidationCheck:
      type: object
      required: [name, status]
      properties:
        name:
          type: string
        status:
          type: string
          enum: [pass, fail, warn]
        code:
          type: string
        message:
          type: string
        path:
          type: string
          nullable: true

    LogEntry:
      type: object
      properties:
        timestamp:
          type: string
          format: date-time
        level:
          type: string
          enum: [debug, info, warn, error]
        message:
          type: string
        request_id:
          type: string
        version_id:
          type: string
          format: uuid
          nullable: true
        metadata:
          type: object
        redacted:
          type: boolean

    LogList:
      type: object
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/LogEntry'
        next_cursor:
          type: string
          nullable: true

    AppList:
      type: object
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/App'
        next_cursor:
          type: string
          nullable: true

    VersionList:
      type: object
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/AppVersion'
        next_cursor:
          type: string
          nullable: true

    ShareList:
      type: object
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/AppShare'
        next_cursor:
          type: string
          nullable: true

    Error:
      type: object
      required: [code, message]
      properties:
        code:
          type: string
          example: CAPABILITY_APPROVAL_REQUIRED
        message:
          type: string
        request_id:
          type: string
        details:
          type: object



---

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

| Code | Meaning |
|---:|---|
| `0` | Valid |
| `2` | Manifest/schema error |
| `3` | Policy violation |
| `4` | Approval required |
| `5` | Authentication/authorization error |
| `10` | Platform/network error |

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

| CLI | API |
|---|---|
| `capsule app get` | `GET /apps/{appId}` |
| `capsule validate` | `POST /apps/{appId}/validate` |
| `capsule publish` | `POST /apps/{appId}/publish` |
| `capsule status` | `GET /apps/{appId}/operations/{operationId}` |
| `capsule versions` | `GET /apps/{appId}/versions` |
| `capsule rollback` | `POST /apps/{appId}/rollback` |
| `capsule share add` | `POST /apps/{appId}/shares` |
| `capsule share list` | `GET /apps/{appId}/shares` |
| `capsule share revoke` | `DELETE /apps/{appId}/shares/{shareId}` |
| `capsule logs` | `GET /apps/{appId}/logs` |

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
