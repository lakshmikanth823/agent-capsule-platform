# AI Coding Agent Guide: Software Capsule Platform

This guide is written specifically for AI coding agents building, validating, testing, and deploying applications on the Software Capsule Platform.

---

## 1. Platform Mental Model

A **Software Capsule** is a self-contained, isolated micro-application:
- **Runtime**: Blessed Node.js 22 + TypeScript.
- **Origin & Network**: Runs with `--network=none` by default (zero outbound access unless explicitly declared in `egress`).
- **Filesystem**: Application code is mounted strictly read-only (`/app:ro`).
- **Database**: Per-capsule SQLite file mounted outside code at `/data/app.sqlite:rw`.
- **Identity**: Edge proxy authenticates users and injects a cryptographically signed `x-capsule-identity` JWT header.
- **Storage**: Blobs and uploads go through the platform SDK (`/data/blobs:rw`), not arbitrary disk paths.

---

## 2. The Capsule Manifest (`capsule.manifest.yaml`)

Every application root must contain a valid `capsule.manifest.yaml`.

### Complete Canonical Template
```yaml
apiVersion: capsule/v1alpha1
id: leave-tracker
name: Leave Tracker
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
egress: []
sharing:
  default: org
limits:
  cpu: small
  memory_mb: 256
  request_timeout_s: 30
```

### Critical Invariants to Remember
1. `shape`: Must be `web-app`.
2. `runtime`: Must be `node22`.
3. `roles`: Declare every application role you intend to assign to users or check in code.
4. `egress`: Default is `[]` (deny all). Only add external hostnames if external networking is required.
5. `sharing.default`: Either `org` (accessible to all members of the organization) or `private` (accessible only to explicitly shared users).

---

## 3. Platform SDK (`@capsule/sdk`)

Always use `@capsule/sdk` inside your application code (`src/index.ts`).

### 3.1 Database Access (`sdk.db`)
```typescript
import { getDatabase } from '@capsule/sdk';

const db = getDatabase();

// Execute DDL or writes
db.exec(`CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, title TEXT, user_id TEXT);`);
const res = db.execute('INSERT INTO items (title, user_id) VALUES (?, ?)', ['My Item', 'usr-123']);
console.log('Inserted ID:', res.lastInsertRowid);

// Query rows
const items = db.query('SELECT * FROM items WHERE user_id = ?', ['usr-123']);
const item = db.get('SELECT * FROM items WHERE id = ?', [1]);

// Atomic transactions (single-writer guarantee)
db.transaction(() => {
  db.execute('UPDATE accounts SET balance = balance - 50 WHERE id = 1');
  db.execute('UPDATE accounts SET balance = balance + 50 WHERE id = 2');
});
```

### 3.2 Verified Identity (`sdk.getIdentity`)
```typescript
import http from 'node:http';
import { getIdentity, type IdentityContext } from '@capsule/sdk';

const server = http.createServer((req, res) => {
  // Automatically verifies HMAC-SHA256 signature, audience, and expiry
  const identity: IdentityContext | null = getIdentity(req);

  if (!identity) {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Unauthorized' }));
    return;
  }

  // Check roles declared in capsule.manifest.yaml
  if (identity.hasRole('manager')) {
    // Manager logic...
  }

  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ user: identity.userId, roles: identity.roles }));
});
```

### 3.3 Platform Blob Storage (`sdk.files`)
```typescript
import { getFiles } from '@capsule/sdk';

const files = getFiles();

// Put file
await files.put('docs/spec.pdf', pdfBuffer, { contentType: 'application/pdf' });

// Get file
const file = await files.get('docs/spec.pdf');
if (file) {
  console.log('File size:', file.size);
}

// List files
const list = await files.list('docs');
```

---

## 4. CLI Workflow for AI Agents

Always use the `--json` flag when running CLI commands to receive structured JSON responses.

### 4.1 CLI Command Cheatsheet
| Command | Purpose |
|---|---|
| `capsule login --user <email> --json` | Authenticate session |
| `capsule init [appName] --json` | Scaffold new starter project |
| `capsule validate --json` | Offline manifest validation (check before publish) |
| `capsule dev --json` | Start local emulator on laptop |
| `capsule publish --json` | Idempotently deploy project to platform |
| `capsule publish --dry-run --json` | Check admission & policy without deploying |
| `capsule share add --role <role> --user <email> --json` | Grant app role to a user |
| `capsule share list --json` | List active shares |
| `capsule unshare <shareId> --json` | Revoke a share |
| `capsule status --json` | Query active deployment status |
| `capsule versions --json` | List version history |
| `capsule logs --tail 50 --json` | Retrieve container logs |

### 4.2 Offline Validation Exit Codes
When running `capsule validate --json`:
- `0`: Valid
- `2`: Manifest or schema error (`invalid_manifest`, `schema_error`)
- `3`: Policy violation
- `4`: Approval required (`capability_approval_required`)
- `5`: Authentication/authorization error
- `10`: Platform network error

---

## 5. Common Errors and Programmatic Fixes

When a command fails with `--json`, the output conforms to:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "field": "optional.field.path",
    "hint": "Actionable next steps"
  }
}
```

### Error 1: `SCHEMA_VALIDATION_FAILED` (Exit Code: 2)
- **Cause**: A required field in `capsule.manifest.yaml` is missing, misspelled, or has an invalid value.
- **Agent Fix**:
  1. Inspect `field` (e.g. `limits.memory_mb`).
  2. Read the `hint` (e.g. `Must be one of: 128, 256, 512, 1024`).
  3. Edit `capsule.manifest.yaml` to correct the field.
  4. Run `capsule validate --json` to verify the fix.

### Error 2: `UNDECLARED_ROLE` (Exit Code: 2 / HTTP 400)
- **Cause**: Calling `capsule share add --role manager` when `manager` is not declared in `capsule.manifest.yaml:roles`.
- **Agent Fix**:
  1. Add `manager` under `roles:` in `capsule.manifest.yaml`.
  2. Run `capsule publish --json` to deploy the updated version with the new role declaration.
  3. Re-run `capsule share add --role manager --json`.

### Error 3: `CAPABILITY_APPROVAL_REQUIRED` (Exit Code: 4)
- **Cause**: The application requested elevated capabilities (e.g. connector service identity or cross-capsule egress).
- **Agent Fix**:
  - An AI agent **cannot** self-approve capability escalation.
  - Inform the human operator that capability escalation approval from the app owner is required.

### Error 4: `VERSION_CONFLICT` / `IDEMPOTENCY_CONFLICT` (Exit Code: 2 / HTTP 409)
- **Cause**: Publishing with `--expected-version <N>`, but another deployment already bumped the version to `<N+1>`.
- **Agent Fix**:
  1. Run `capsule versions --json` to retrieve the current latest version number.
  2. Re-publish using `--expected-version <current_version>`.

### Error 5: `SQLITE_FULL` (Runtime Error)
- **Cause**: Database writes exceeded `PRAGMA max_page_count` (the capsule's disk quota).
- **Agent Fix**:
  1. If legitimate data growth, increase `limits.db_max_mb` in `capsule.manifest.yaml` (up to platform quota).
  2. Clean up obsolete rows using `db.execute('DELETE FROM ...')` followed by `db.exec('VACUUM;')`.

### Error 6: `UNAUTHENTICATED` (Exit Code: 5)
- **Cause**: No valid session token in `~/.capsule/config.json`.
- **Agent Fix**:
  - Run `capsule login --user <email> --json` before running control-plane commands.
