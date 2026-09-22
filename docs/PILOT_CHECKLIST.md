# Pilot Customer Checklist

**Document Version:** 1.0 — Pre-Pilot  
**Date:** 2026-09-22  
**Audience:** First pilot customer team and their technical lead

> [!CAUTION]
> This is a pre-general-availability platform. Some production hardening items are still outstanding (see docs/SECURITY_REVIEW_FINAL.md). Review Known Limits carefully before deploying any application that handles regulated or sensitive data.

---

## Part 1: What You Can Do

The Capsule Platform lets your team publish internal web applications as **capsules** — isolated, managed, versioned micro-applications. You can:

- ✅ **Publish TypeScript/Node.js web apps** as capsules with one command (`capsule publish`)
- ✅ **Share apps** with users, groups, or your whole organization
- ✅ **Use structured data** (SQLite per app, automatic snapshots, safe rollback)
- ✅ **Declare external API calls** in your manifest — all other outbound traffic is blocked by default
- ✅ **Call LLMs** (OpenAI, Anthropic, Gemini) via the SDK — your app never handles API keys
- ✅ **Integrate with Google Sheets** as a viewer — the platform uses your users' OAuth tokens
- ✅ **Set up SSO** (OIDC/SAML) and SCIM directory sync for enterprise authentication
- ✅ **Get audit logs** of every action, with cryptographic tamper evidence
- ✅ **Manage ownership, expiry, and lifecycle** from the dashboard and CLI

---

## Part 2: Known Limits

### Hard Limits (enforced, cannot be changed without a platform update)

| Limit                   | Value                                                                              |
| ----------------------- | ---------------------------------------------------------------------------------- |
| App shape               | `web-app` only (no background workers, no scheduled jobs, no pub/sub in Phase 0–1) |
| Runtime                 | Node.js 22 only                                                                    |
| Memory per app          | 256 MB default; 512 MB maximum configurable via manifest                           |
| CPU per app             | 0.5 vCPU default; 2.0 vCPU maximum                                                 |
| Disk (SQLite)           | 50 MB default; 200 MB maximum configurable per manifest                            |
| File storage (blobs)    | 100 MB per app                                                                     |
| Egress bandwidth        | 100 MB/day default per app                                                         |
| Processes per container | 64 maximum (`--pids-limit`)                                                        |
| LLM monthly budget      | Per-app budget declared in manifest                                                |
| LLM models              | Only models allowed by your Environment Profile                                    |

### Soft Limits (defaults; can be adjusted by your org admin)

| Limit                     | Default            | Configurable                   |
| ------------------------- | ------------------ | ------------------------------ |
| Apps per organization     | 100                | Yes — contact platform support |
| Versions per app retained | 50                 | Yes                            |
| Audit log retention       | 90 days            | Yes (minimum: 30 days)         |
| Share expiry              | Never (unless set) | Yes per share                  |
| Inactivity expiry         | 90 days            | Yes per app or org default     |
| Content logging for AI    | Off                | Opt-in per org                 |

### Architectural Limits (not configurable)

- **No app-to-app communication.** Capsules cannot call each other directly. Each capsule is network-isolated. Communication must go through declared external APIs.
- **No server-side events or WebSockets.** Only HTTP request/response is supported in Phase 0.
- **No binary/native modules** that bypass Node.js standard library. The sandbox blocks raw socket access.
- **No persistent background processes.** Code runs only when an HTTP request arrives.
- **SQLite only** for structured data. No external database connections unless declared as a connector.
- **Google Sheets read-only.** The `sheets.read` connector supports viewer identity only. No write access.
- **LLM model output is untrusted.** Tool calling (`function_calling`) is disabled at the platform level. LLM responses must be treated as user-controlled data in your application code.

---

## Part 3: Security Posture During Pilot

### What the platform does for you

- **Origin isolation:** Every app runs on its own subdomain (`<app-id>.apps.example.com`). Session cookies are scoped to that subdomain only.
- **Default-deny egress:** Your app cannot make outbound network calls to anything not explicitly declared in its manifest.
- **SSRF protection:** The egress proxy blocks RFC 1918 addresses, cloud metadata endpoints (169.254.169.254), and DNS rebinding.
- **Sandbox isolation:** Production runs with gVisor (`runsc`), a user-space kernel. Guest code never executes host kernel syscalls.
- **No raw secrets:** Your app never receives API keys, OAuth tokens, or database passwords. The platform handles all credentials.
- **Role-based access:** Only org `owner` and `editor` roles can share, publish, or change settings. The `user` role has read-only capability access.

### What you are responsible for during pilot

- **Application code security:** The platform sandbox is a security boundary for the host system, not a substitute for secure coding. Your app is responsible for: SQL injection prevention, XSS escaping, input validation, authorization checks using `sdk.getIdentity()` roles.
- **Content Security Policy:** The platform sets a baseline CSP. If your app uses inline scripts or third-party resources, review the CSP configuration with the platform team.
- **Data classification:** Do not publish apps that handle regulated data (PHI, PII beyond names/emails, financial records, passwords) during the pilot without explicit sign-off from the platform team. See Part 6 for data handling.
- **Manifest capability review:** Every capability you declare in your manifest (egress hosts, connectors, AI access) is visible to org admins. Declare only what your app actually needs.

### Known open security items (accepted for pilot with mitigations)

> [!WARNING]
> The following items from docs/SECURITY_REVIEW_FINAL.md are outstanding. Mitigations are in place but full fixes are targeted for GA.

| ID      | Issue                                  | Pilot Mitigation                                                              |
| ------- | -------------------------------------- | ----------------------------------------------------------------------------- |
| SEC-001 | Raw JSON identity bypass in SDK        | `CAPSULE_EMULATOR` not set in staging/prod; gVisor sets `NODE_ENV=production` |
| SEC-002 | Identity signing secret in sandbox env | Do not deploy apps with access to sensitive systems during pilot              |
| SEC-007 | Share revocation ~seconds delayed      | Workaround: restart edge proxy after bulk revocations                         |
| SEC-009 | Org auto-provisioning from OIDC claim  | `enforce_sso=true` set for your domain prevents this                          |
| SEC-012 | `NODE_ENV=development` auth bypass     | gVisor driver explicitly sets `NODE_ENV=production` in all sandboxes          |

---

## Part 4: Support Process

### During Pilot

| Channel                      | Use for                                    | SLA                            |
| ---------------------------- | ------------------------------------------ | ------------------------------ |
| pilot-support@example.com    | Questions, unexpected errors               | Reply within 1 business day    |
| security@example.com         | Security concerns, suspected data exposure | Reply within 4 hours           |
| GitHub Issues (private repo) | Bug reports, feature requests              | Triaged within 2 business days |

### Escalation

If you cannot reach support via email within stated SLA, contact your named platform engineer directly.

### Incident Response

In case of a security incident (suspected data access, unexpected behavior, error in audit logs):

1. **Do not attempt to fix it yourself.** Do not publish new versions or change permissions.
2. **Contact security@example.com immediately** with a description and your `organization_id`.
3. Platform team will use the kill switch (`POST /v1/admin/kill-switch`) to suspend affected apps within minutes if needed.
4. Platform team will pull audit logs and provide a timeline within 4 hours.
5. You will receive a post-incident report within 5 business days.

### Self-service tools

```bash
# View audit log for your org
capsule audit list --org <org-id>

# Verify audit log integrity
capsule audit verify --org <org-id>

# Check current app status
capsule status --app <app-id>

# See who has access
capsule status --app <app-id> --show-shares

# Revoke all sessions (e.g. for a compromised account)
# Contact platform support — bulk session revocation requires admin access
```

---

## Part 5: Onboarding Steps

### Before your first publish

1. **Register your domain** — your org admin must verify your email domain (`@yourcompany.com`) in the dashboard under Settings → Identity.
2. **Set up SSO** — Configure your OIDC or SAML IdP under Settings → Identity Providers. Enable `Enforce SSO` for your domain.
3. **Set up SCIM** (optional but recommended) — Connect your IdP's SCIM sync so that departing employees are automatically deprovisioned.
4. **Review your Environment Profile** — Your org admin sets the allowed runtimes, capabilities, AI models, and egress ceilings. Review with your team before publishing.
5. **Install the CLI** — `npm install -g @capsule/cli` then `capsule login`.
6. **Try the example app** — `capsule init --template leave-tracker` then `capsule dev` to test locally.

### Publishing your first app

```bash
# 1. Validate manifest (offline, no network required)
capsule validate

# 2. Publish
capsule publish --message "Initial pilot release"

# 3. Share with your team
capsule share --app <app-id> --email teammate@yourcompany.com --role employee

# 4. Check status
capsule status --app <app-id>
```

### Checklist for each app before sharing with users

- [ ] `capsule validate` passes with zero warnings
- [ ] Manifest declares only the capabilities the app actually uses
- [ ] Egress allowlist contains only domains the app needs
- [ ] AI monthly budget is set if using `capabilities.ai`
- [ ] App has been tested with `capsule dev` locally
- [ ] At least one org admin is set as the nominated owner (`nominated_owner_user_id`) in case the app owner leaves
- [ ] Expiry policy reviewed: does this app need a lifecycle end date?

---

## Part 6: Data Handling

### What data the platform stores

| Data Category                                  | Storage Location                | Retention                               | Encryption      |
| ---------------------------------------------- | ------------------------------- | --------------------------------------- | --------------- |
| Application bundles (code)                     | S3 (versioned)                  | Until app deleted + 30 days             | AES-256 at rest |
| SQLite databases (app data)                    | Sandbox host EBS + S3 snapshots | Until app purged (per retention policy) | AES-256 at rest |
| File blobs                                     | S3                              | Until deleted by app or purge           | AES-256 at rest |
| Audit logs                                     | PostgreSQL (RDS)                | 90 days default                         | AES-256 at rest |
| Connector credentials (OAuth tokens, API keys) | PostgreSQL (encrypted field)    | Until disconnected                      | AES-256-GCM     |
| LLM prompt/response content                    | NOT stored by default           | N/A                                     | N/A             |
| LLM usage metadata (token counts, cost)        | PostgreSQL                      | 90 days                                 | AES-256 at rest |

### What the platform does NOT log

- Prompt content or LLM response content (metadata only, by default)
- Raw connector payloads or query parameters
- User activity within your app (what users click, what they type)
- Session cookies or authentication tokens

### Data export

You can export all your app's data at any time:

```bash
# Export capsule data archive (code + database + blobs)
GET /v1/apps/{app-id}/export-data
# Returns a signed S3 URL to a ZIP archive
```

This export is also automatically offered before any app is permanently deleted.

### Data residency

All data is stored in AWS `us-east-1` (N. Virginia) during the pilot. If you have data residency requirements for other regions, contact the platform team before onboarding.

### Data Processing Agreement

> [!IMPORTANT]
> A Data Processing Agreement (DPA) covering the platform's role as a data processor for any personal data stored in capsule databases must be signed before going live with production user data. Contact legal@example.com.

---

## Part 7: Things We Ask You to Tell Us

As a pilot customer, your feedback directly shapes the GA release. Please report:

1. **Any unexpected 4xx or 5xx error** — with the full JSON error body and your `organization_id`.
2. **Performance issues** — if a capsule takes more than 2 seconds to respond on a warm request, or more than 5 seconds cold start.
3. **Missing capabilities** — if your app needs something not in the current capability set.
4. **Confusing CLI output** — if any command output is unclear or misleading.
5. **Documentation gaps** — if the Agent Guide (`capsule mcp get_agent_guide`) is missing something your AI agent needed.

### Things we will NOT ask you to do

- We will never ask for your `--json` output that contains tokens or credentials.
- We will never ask you to share your `capsule-token-*` publish tokens.
- We will never ask you to change your OIDC client secret via email or chat.

---

## Appendix: Quick Reference

```bash
# Install
npm install -g @capsule/cli

# Login
capsule login

# Init new app
capsule init

# Local development (hot reload)
capsule dev

# Validate manifest
capsule validate

# Publish new version
capsule publish --message "description"

# Share with a user
capsule share --app <id> --email user@co.com --role employee

# Revoke a share
capsule unshare --app <id> --share-id <share-id>

# Check status
capsule status --app <id>

# View logs
capsule logs --app <id> --tail 100

# List versions
capsule versions --app <id>

# Rollback
capsule rollback --app <id> --to-version 3 --confirm

# View audit log
capsule audit list --org <org-id>

# Inventory of all apps
capsule inventory --org <org-id>
```
