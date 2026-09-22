# Model Context Protocol (MCP) Adapter Specification & Setup Guide (Prompt 26)

**Date**: 2026-09-22  
**Package**: `@capsule/mcp-server` (`packages/mcp-server`)  
**Status**: Production-Ready

---

## 1. Overview & Architectural Principles

The **Capsule MCP Server** (`@capsule/mcp-server`) is a thin adapter exposing the Software Capsule Platform API and offline CLI validation logic to AI coding agents, desktop IDEs, and autonomous developer workflows via the official **Model Context Protocol (MCP)**.

### Core Architectural Guarantees:

1. **Zero Privilege Escalation**:
   - The MCP server is strictly a thin wrapper over the existing REST API (`http://localhost:8000`) and the `@capsule/manifest-schema` offline validator.
   - It possesses **no privileges of its own** and can never perform any operation the API would reject.
2. **No Secrets in Tool Arguments**:
   - Tool input schemas **never** expose or accept `token`, `api_key`, `secret`, or `password` parameters.
   - Authentication is retrieved automatically using the exact same mechanisms as the CLI:
     - Active session credentials in `~/.capsule/config.json` (from `capsule login`).
     - Or the `CAPSULE_TOKEN` / `CAPSULE_API_KEY` environment variables.
3. **Explicit Confirmation for Destructive & Broad Actions**:
   - Any action with irreversible or broad blast radius requires an explicit `confirm: true` parameter:
     - **Rollback with Data Restore** (`mode: "code_and_data"`): Overwrites active SQLite database with an earlier snapshot.
     - **Org-Wide Sharing** (`scope: "org"` or `group_name: "*"`): Grants access to all organization members.
     - **Service Identity Publication** (`acts_as: "service"`): Grants autonomous non-viewer service credentials.
     - **Share Revocation** (`unshare`): Immediately terminates active user or group access.
   - If `confirm: true` is missing, the tool immediately halts and returns a structured `CONFIRMATION_REQUIRED` error explaining the blast radius.
4. **Untrusted Platform Data Quarantining**:
   - Everything returned from the platform (stdout/stderr container logs, app descriptions, app names, user error messages) is strictly treated as untrusted data.
   - Outputs are encapsulated in anti-prompt-injection delimiters (`<<< UNTRUSTED_PLATFORM_DATA >>>`) and structured quarantine objects to prevent model instruction hijacking.
5. **Structured Error Passthrough**:
   - Control plane validation errors (`code`, `message`, `field`, `hint`) are passed through unchanged in MCP tool error envelopes (`isError: true`), allowing AI agents to autonomously inspect, diagnose, and fix problems.

---

## 2. Tools Catalog

The adapter provides 9 tools covering the full lifecycle:

| Tool Name           | Type                | Description                                                                   | Confirmation Required?  |
| :------------------ | :------------------ | :---------------------------------------------------------------------------- | :---------------------: |
| `validate_manifest` | Read-only / Offline | Validates `capsule.manifest.yaml` offline against schema and policy ceilings. |           No            |
| `publish`           | Mutation / Online   | Publishes a version to the platform with pre-deployment SQLite snapshot.      | If `acts_as: "service"` |
| `share`             | Mutation / Online   | Assigns application roles to users or groups.                                 |    If `scope: "org"`    |
| `unshare`           | Mutation / Online   | Revokes active sharing assignment.                                            |  Yes (`confirm: true`)  |
| `status`            | Read-only / Online  | Inspects capsule runtime state, version, and live URL.                        |           No            |
| `logs`              | Read-only / Online  | Retrieves recent stdout/stderr logs (quarantined).                            |           No            |
| `versions`          | Read-only / Online  | Lists published version history and snapshot refs.                            |           No            |
| `rollback`          | Mutation / Online   | Rolls back code or code+data to a prior version.                              |   If `code_and_data`    |
| `get_agent_guide`   | Read-only / Offline | Returns canonical agent instructions (`docs/AGENT_GUIDE.md`).                 |           No            |

---

### Tool Schemas & Examples

#### 1. `validate_manifest`

```json
{
  "manifest_content": "apiVersion: capsule/v1alpha1\nid: my-app\nname: My App\nshape: web-app\nruntime: node22\nroles: [user]\nlimits:\n  cpu: small\n  memory_mb: 256\n  request_timeout_s: 30\n",
  "path": "capsule.manifest.yaml"
}
```

#### 2. `publish`

```json
{
  "app_id": "leave-tracker",
  "description": "Added manager approval workflow",
  "expected_version": 2,
  "confirm": false
}
```

_Note: Set `"confirm": true` if the manifest requests service identity connectors (`acts_as: service`)._

#### 3. `share`

```json
// Individual User Share:
{
  "app_id": "leave-tracker",
  "role": "manager",
  "user_email": "manager@example.com"
}

// Org-Wide Share (Requires confirm: true):
{
  "app_id": "leave-tracker",
  "role": "employee",
  "scope": "org",
  "confirm": true
}
```

#### 4. `unshare`

```json
{
  "app_id": "leave-tracker",
  "share_id": "c6a23b9d-4789-4112-9c3f-801a21e42f90",
  "confirm": true
}
```

#### 5. `status`

```json
{
  "app_id": "leave-tracker"
}
```

#### 6. `logs`

```json
{
  "app_id": "leave-tracker",
  "tail": 50
}
```

#### 7. `versions`

```json
{
  "app_id": "leave-tracker"
}
```

#### 8. `rollback`

```json
// Code-Only Rollback:
{
  "app_id": "leave-tracker",
  "target_version": 1,
  "mode": "code_only"
}

// Code-and-Data Restore (Requires confirm: true):
{
  "app_id": "leave-tracker",
  "target_version": 1,
  "mode": "code_and_data",
  "confirm": true,
  "reason": "Restoring clean database prior to corrupt migration"
}
```

#### 9. `get_agent_guide`

```json
{
  "section": "manifest"
}
```

---

## 3. Client Setup Configurations

### A. Claude Desktop

Add the following to your Claude Desktop configuration file:

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "capsule": {
      "command": "node",
      "args": ["E:/Cloud/capsule-platform/packages/mcp-server/dist/cli.js"],
      "env": {
        "CONTROL_PLANE_URL": "http://localhost:8000",
        "CAPSULE_TOKEN": "your-scoped-token-or-session-token",
        "APP_DOMAIN": "apps.localhost"
      }
    }
  }
}
```

_(If using global npm installation or npx: `"command": "capsule-mcp"`)_

---

### B. Cursor

Add the following to your Cursor configuration (`.cursor/mcp.json` or Cursor Settings -> Features -> MCP Servers -> Add New MCP Server):

```json
{
  "mcpServers": {
    "capsule-platform": {
      "command": "node",
      "args": ["E:/Cloud/capsule-platform/packages/mcp-server/dist/cli.js"],
      "env": {
        "CONTROL_PLANE_URL": "http://localhost:8000",
        "CAPSULE_TOKEN": "your-scoped-token-or-session-token"
      }
    }
  }
}
```

---

### C. Google Antigravity

Add the server to your Antigravity global configuration (`~/.gemini/antigravity/mcp_config.json`) or workspace `.agy/mcp.json`:

```json
{
  "mcpServers": {
    "capsule": {
      "command": "node",
      "args": ["E:/Cloud/capsule-platform/packages/mcp-server/dist/cli.js"],
      "env": {
        "CONTROL_PLANE_URL": "http://localhost:8000",
        "CAPSULE_TOKEN": "your-scoped-token-or-session-token",
        "NODE_ENV": "development"
      }
    }
  }
}
```

---

## 4. Environment Variables

| Variable             | Description                                                                 | Default                       |
| :------------------- | :-------------------------------------------------------------------------- | :---------------------------- |
| `CONTROL_PLANE_URL`  | Base URL of the control plane API.                                          | `http://localhost:8000`       |
| `CAPSULE_TOKEN`      | Authentication session token or scoped publish token (`capsule-token-...`). | From `~/.capsule/config.json` |
| `CAPSULE_CONFIG_DIR` | Directory containing CLI session config (`config.json`).                    | `~/.capsule`                  |
| `APP_DOMAIN`         | Subdomain domain suffix for live applications.                              | `apps.localhost`              |

---

## 5. Structured Error Codes Reference

When an error occurs, the server responds with `isError: true` and a structured payload:

```json
{
  "code": "CONFIRMATION_REQUIRED",
  "message": "Rollback with data restore ('code_and_data') will overwrite the active SQLite database with the snapshot from version 1 and cause irreversible data loss for intervening records.",
  "field": "confirm",
  "hint": "Re-invoke rollback with 'confirm': true to authorize database snapshot restoration."
}
```

| Error Code                     | Meaning                                                        | Remediation Action                                   |
| :----------------------------- | :------------------------------------------------------------- | :--------------------------------------------------- |
| `CONFIRMATION_REQUIRED`        | Broad or destructive action requested without `confirm: true`. | Re-run tool with `"confirm": true`.                  |
| `UNAUTHENTICATED`              | No valid session or `CAPSULE_TOKEN` found.                     | Run `capsule login` or set `CAPSULE_TOKEN`.          |
| `PERMISSION_DENIED`            | Caller lacks owner/editor platform role for app or share.      | Contact organization owner.                          |
| `CAPABILITY_APPROVAL_REQUIRED` | Manifest requests escalated or sensitive capabilities.         | Await org admin approval or narrow manifest.         |
| `QUOTA_EXCEEDED`               | Memory, timeout, or storage quota exceeded.                    | Reduce limits in manifest or upgrade org quota.      |
| `MANIFEST_NOT_FOUND`           | `capsule.manifest.yaml` not found at path.                     | Pass `manifest_content` or run in project directory. |
| `VERSION_NOT_FOUND`            | Target rollback version does not exist.                        | Use `versions` tool to inspect available versions.   |
| `APP_NOT_FOUND`                | Specified capsule does not exist in registry.                  | Verify `app_id` or run `publish` to create it.       |
