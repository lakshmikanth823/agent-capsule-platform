# Capsule Platform SDK (`@capsule/sdk`)

The `@capsule/sdk` package provides the standard application library for the blessed Node.js 22 + TypeScript Capsule shape.

> [!NOTE]
> The platform (sandbox driver, edge proxy, and control plane), not this SDK, is the security boundary. The SDK provides convenient, typed APIs that conform to platform contracts.

---

## 1. Installation

In your Capsule application:

```bash
npm install @capsule/sdk
```

---

## 2. Per-Capsule Database (`sdk.db`)

Each Capsule receives an isolated SQLite database file stored outside the application code directory (`/data/app.sqlite` in containers, `./.capsule/local.db` in local emulator mode).

### Features
- **WAL Mode & Normal Sync**: Configured automatically for high concurrency.
- **Single-Writer Guarantee**: Transactions use immediate write locks (`BEGIN IMMEDIATE`).
- **Native Size Limit**: Enforced via `PRAGMA max_page_count` based on manifest limits (default 50MB). Writes exceeding the quota reject with `SQLITE_FULL`.
- **Clean Export**: Supports non-locking exports via `exportDatabase(path)` using `VACUUM INTO`.

### Examples for AI Agents

#### Initialize Schema and Insert Record
```typescript
import { getDatabase } from '@capsule/sdk';

const db = getDatabase();

// Create table if not exists
db.exec(`
  CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
  );
`);

// Insert record
const result = db.execute(
  'INSERT INTO items (user_id, title) VALUES (?, ?)',
  ['user-123', 'My First Item']
);
console.log('Inserted row ID:', result.lastInsertRowid);
```

#### Query Records
```typescript
import { getDatabase } from '@capsule/sdk';

const db = getDatabase();

interface Item {
  id: number;
  user_id: string;
  title: string;
  created_at: string;
}

// Query all matching rows
const userItems = db.query<Item>(
  'SELECT * FROM items WHERE user_id = ? ORDER BY id DESC',
  ['user-123']
);

// Query single row
const item = db.get<Item>(
  'SELECT * FROM items WHERE id = ?',
  [1]
);
```

#### Atomic Transactions
```typescript
import { getDatabase } from '@capsule/sdk';

const db = getDatabase();

db.transaction(() => {
  db.execute('UPDATE accounts SET balance = balance - 100 WHERE id = ?', [1]);
  db.execute('UPDATE accounts SET balance = balance + 100 WHERE id = ?', [2]);
});
```

---

## 3. Verified Identity (`sdk.getIdentity`)

The edge proxy authenticates users and forwards requests with a cryptographically signed `x-capsule-identity` JWT header.

### Features
- **Signature Verification**: Validates HMAC-SHA256 signature using platform secrets.
- **Audience Check**: Validates `aud` matches `capsule:<app_id>`.
- **Expiration Check**: Validates `exp` timestamp.
- **Role Helpers**: Helper methods `hasRole()`, `hasAnyRole()`, and `isMemberOf()`.

### Examples for AI Agents

#### Route Protection and Role Checking
```typescript
import http from 'node:http';
import { getIdentity, type IdentityContext } from '@capsule/sdk';

const server = http.createServer((req, res) => {
  const identity: IdentityContext | null = getIdentity(req);

  if (!identity) {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Unauthorized' }));
    return;
  }

  // Check application roles declared in capsule.manifest.yaml
  if (!identity.hasAnyRole('manager', 'admin')) {
    res.writeHead(403, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Requires manager role' }));
    return;
  }

  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({
    message: `Hello ${identity.email}`,
    userId: identity.userId,
    roles: identity.roles,
  }));
});
```

---

## 4. Platform File / Blob Storage (`sdk.files`)

Capsule applications store files and blobs through the platform, never via arbitrary direct disk access.

### Features
- **Path Traversal Defense**: Automatically blocks `..` attacks and escapes outside storage root.
- **Content-Type Metadata**: Preserves MIME types across put and get.
- **Isolated Per-Capsule Storage**: Placed in `/data/blobs` in container runtime or `./.capsule/blobs` in emulator.

### Examples for AI Agents

#### Store, Retrieve, and List Files
```typescript
import { getFiles } from '@capsule/sdk';

const files = getFiles();

// 1. Upload / save file
const saved = await files.put(
  'documents/invoice-001.pdf',
  pdfBuffer,
  { contentType: 'application/pdf' }
);
console.log('Saved file size:', saved.size);

// 2. Read file
const file = await files.get('documents/invoice-001.pdf');
if (file) {
  console.log('Content-Type:', file.contentType);
  console.log('Data Buffer:', file.data);
}

// 3. List files with prefix
const docs = await files.list('documents');
for (const doc of docs) {
  console.log(`File: ${doc.path}, Size: ${doc.size} bytes`);
}

// 4. Delete file
await files.delete('documents/invoice-001.pdf');
```

---

## 5. Local Emulator Mode

To run and test your Capsule application on a developer laptop without running the full platform:

### Environment Variables
When running outside Docker:
- `CAPSULE_EMULATOR=true`
- `DATABASE_PATH=./.capsule/local.db`
- `CAPSULE_BLOB_DIR=./.capsule/blobs`

In emulator mode:
1. `sdk.db` automatically creates `./.capsule/local.db`.
2. `sdk.files` stores blobs in `./.capsule/blobs`.
3. `sdk.getIdentity(req)` provides a mock development user (`dev-user-001` with roles `employee`, `manager`) when no `x-capsule-identity` header is present.

### Running Locally
```bash
npx tsx src/index.ts
```
The application starts and operates with zero platform dependencies.
