# Security Review — Final (Pre-Pilot Gate)

**Reviewer:** Independent review (Prompt 27 — no prior reports trusted)  
**Date:** 2026-09-22  
**Scope:** All code read directly from source. No trust placed in STATUS.md or prior review claims.  
**Method:** Manual code audit of 15 source files; cross-referencing test coverage.  
**Verdict:** Platform has a strong security architecture with several concrete vulnerabilities that MUST be fixed before any real-user pilot.

---

## Summary Table

| ID      | Surface                                                           | Severity     | Fix Required Before Pilot |
| ------- | ----------------------------------------------------------------- | ------------ | ------------------------- |
| SEC-001 | Identity header — raw JSON bypass                                 | **CRITICAL** | YES                       |
| SEC-002 | Identity secret leaked into sandbox env                           | **CRITICAL** | YES                       |
| SEC-003 | Connector viewer identity — signature bypass fallback             | **CRITICAL** | YES                       |
| SEC-004 | CORS wildcard with credentials on control plane                   | **CRITICAL** | YES                       |
| SEC-005 | Platform role self-elevation via JWT claim                        | **HIGH**     | YES                       |
| SEC-006 | App key unverified — cross-capsule egress impersonation           | **HIGH**     | YES                       |
| SEC-007 | Sharing revocation — stale in-memory cache window                 | **HIGH**     | YES                       |
| SEC-008 | Edge proxy uses hardcoded mock token to call control plane        | **HIGH**     | YES                       |
| SEC-009 | OIDC org provisioned from claim — org takeover risk               | **HIGH**     | YES                       |
| SEC-010 | Rollback race — no DB-level lock                                  | **MEDIUM**   | Recommended               |
| SEC-011 | Share by email creates users cross-org without verification       | **MEDIUM**   | YES                       |
| SEC-012 | `NODE_ENV=development` bypasses all identity auth                 | **MEDIUM**   | YES                       |
| SEC-013 | CSP `unsafe-inline` in edge proxy applied to capsule responses    | **MEDIUM**   | Recommended               |
| SEC-014 | Audit log retains connector invocation payload hash — replay risk | **LOW**      | No                        |
| SEC-015 | gVisor ptrace platform — not KVM hardened in CI/test              | **LOW**      | Before GA                 |

---

## Detailed Findings

### SEC-001 — CRITICAL: Identity Header Raw JSON Bypass

**File:** [`packages/sdk/src/identity.ts:132-141`](file:///e:/Cloud/capsule-platform/packages/sdk/src/identity.ts#L132-L141)

```typescript
// Support raw JSON identity header for backward-compatibility with tests/mock callers
if (token.trim().startsWith("{")) {
  try {
    const parsed = JSON.parse(token);
    if (parsed && typeof parsed === "object" && (parsed.sub || parsed.userId)) {
      return createIdentityContext(parsed); // ← NO SIGNATURE CHECK
    }
  } catch {}
}
```

**Impact:** Any capsule application that can set the `x-capsule-identity` header (e.g. by making a direct HTTP call to a connector endpoint that consumes it, or through a proxy misconfiguration) can inject a raw JSON object with any `sub`, `org_id`, `roles`, and `email` it chooses. This bypasses HMAC-SHA256 signature verification entirely. An attacker capsule can impersonate any user or escalate to any role.

**Note:** The edge proxy adds the header after the app's request arrives, but the `x-capsule-identity` header check runs in the SDK inside the capsule (e.g. `requireIdentity(req)`). If the capsule also exposes connector endpoints that consume this header from untrusted caller input, or if the header is forwarded upstream from the sandbox, this path is exploitable.

**Fix:** Remove the raw JSON fallback unconditionally. It was intended for tests only; tests should use `createDevIdentityToken()` to generate properly signed tokens.

---

### SEC-002 — CRITICAL: CAPSULE_IDENTITY_SECRET Leaked into Sandbox Environment

**File:** [`packages/sandbox-driver/src/drivers/gvisor.ts:156-158`](file:///e:/Cloud/capsule-platform/packages/sandbox-driver/src/drivers/gvisor.ts#L156-L158)

```typescript
if (process.env.CAPSULE_IDENTITY_SECRET) {
  dockerArgs.push(
    "-e",
    `CAPSULE_IDENTITY_SECRET=${process.env.CAPSULE_IDENTITY_SECRET}`,
  );
}
```

**Impact:** The HMAC-SHA256 signing secret for identity tokens is injected as a plain environment variable into every sandbox container. Because HS256 is symmetric, any capsule app that reads `process.env.CAPSULE_IDENTITY_SECRET` can:

1. Forge a valid `x-capsule-identity` JWT token for any user, any org, any role.
2. Impersonate `platform_role: "owner"` and make control plane API calls with full administrative access.

This completely undermines the identity security model.

**Fix:** Switch to asymmetric signing (RS256 or Ed25519). The edge proxy holds the private key; sandboxes receive only the public key for verification. Sandboxes can then verify but never forge tokens. This is the same fix called for in STATUS.md Fix 1, but the severity here is independently confirmed as CRITICAL.

---

### SEC-003 — CRITICAL: Connector Viewer Identity — Signature Bypass Fallback

**File:** [`services/control-plane/src/api/connectors.py:64-77`](file:///e:/Cloud/capsule-platform/services/control-plane/src/api/connectors.py#L64-L77)

```python
def parse_viewer_identity(header_value: Optional[str]) -> Optional[Dict[str, Any]]:
    ...
    try:
        if header_value.count(".") == 2:
            ...
            try:
                return jwt.decode(header_value, secret, algorithms=["HS256"], ...)
            except Exception:
                return jwt.decode(header_value, options={"verify_signature": False})  # ← CRITICAL
        return json.loads(header_value)  # ← accepts raw JSON too
    except Exception:
        return None
```

**Impact:** When the first JWT decode fails (e.g. wrong secret, expired token, malformed), the fallback silently decodes the token **without verifying its signature**. An attacker can craft an arbitrary JWT with any `sub`, `org_id`, or role, cause the signature check to fail (e.g. by using a different algorithm or signing key), and the fallback will accept their forged identity. Combined with SEC-001, this allows impersonating any viewer for connector invocations (e.g. Google Sheets reads as any user).

**Fix:** Remove the `verify_signature: False` fallback entirely. A failed decode must be treated as an authentication failure, not an invitation to retry without verification.

---

### SEC-004 — CRITICAL: CORS Wildcard with Credentials on Control Plane

**File:** [`services/control-plane/src/main.py:17-23`](file:///e:/Cloud/capsule-platform/services/control-plane/src/main.py#L17-L23)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # ← Any origin
    allow_credentials=True,    # ← Including cookies
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Impact:** `allow_origins=["*"]` combined with `allow_credentials=True` is a browser-rejected combination per the CORS specification (browsers refuse preflight for `*` + credentials), but FastAPI/Starlette's implementation may still emit `Access-Control-Allow-Origin: *` on non-preflight requests. More critically, this configuration allows any web origin to make credentialed cross-origin requests to the control plane API from a victim's browser, enabling:

- Cross-Site Request Forgery on all admin API endpoints.
- Exfiltration of API responses to attacker-controlled origins.

The control plane should only accept requests from the dashboard domain and the edge proxy domain.

**Fix:** Replace `allow_origins=["*"]` with an explicit allowlist: `[DASHBOARD_DOMAIN, EDGE_PROXY_DOMAIN]`. These should be environment-configurable.

---

### SEC-005 — HIGH: Platform Role Self-Elevation via JWT Claim

**File:** [`services/control-plane/src/auth/dependencies.py:172`](file:///e:/Cloud/capsule-platform/services/control-plane/src/auth/dependencies.py#L172)

```python
platform_role = claims.get("platform_role", "user")
```

**Impact:** With `MockOIDCProvider` (the default when `AUTH_PROVIDER != "google"`), the JWT claims are produced by the mock IdP without any server-side validation of the `platform_role` field. An attacker who can craft a token accepted by the mock OIDC provider (e.g. by signing with the known dev secret) can include `"platform_role": "owner"` in claims and gain full admin privileges on first login. Even with real OIDC providers, if the provider allows custom claims, this is a privilege escalation vector.

**Fix:** For mock/dev OIDC, reject `platform_role` claims that weren't issued by the platform's own provisioning flow. For production: never trust `platform_role` from an external IdP claim; always resolve from the `organization_members` database table.

---

### SEC-006 — HIGH: App Key Unverified — Cross-Capsule Egress Impersonation

**File:** [`services/egress-proxy/src/index.ts:147-169`](file:///e:/Cloud/capsule-platform/services/egress-proxy/src/index.ts#L147-L169)

```typescript
function extractAppKey(req: http.IncomingMessage): string {
  const appKeyHeader = req.headers['x-capsule-key'] || req.headers['x-capsule-id'] || ...;
  if (appKeyHeader) return appKeyHeader;
  ...
  return 'unknown-app';
}
```

**Impact:** The egress proxy identifies which capsule is making a request solely by the `x-capsule-key` or `x-capsule-id` HTTP header. These headers are set by the capsule application code itself — there is no cryptographic proof that the sending container is the capsule it claims to be. A compromised or malicious capsule can send `x-capsule-key: some-other-app` and use the other app's egress allowlist to reach destinations the attacker's own app is not allowed to reach.

**Fix:** In production, the egress proxy should receive the app key via a trusted out-of-band channel (e.g. injected by the sandbox driver at container creation time into a dedicated kernel-level label, or via a mutual TLS client certificate issued per-container, or via a Unix socket per container). The header approach is acceptable for dev only.

---

### SEC-007 — HIGH: Sharing Revocation — Stale In-Memory Cache Window

**File:** [`services/edge-proxy/src/index.ts:180-198`](file:///e:/Cloud/capsule-platform/services/edge-proxy/src/index.ts#L180-L198)

```typescript
// Synchronize shares
for (const s of sharesData.shares || []) {
  if (s.status === 'active') {
    // Only ADDS shares, never removes revoked ones
    if (!alreadyPresent) {
      accessManager.addShare({ ... });
    }
  }
}
```

**Impact:** When shares are synchronized from the control plane, only active shares are added to the in-memory `AccessManager`. Revoked shares are never removed. A user whose share was revoked will continue to have access through the edge proxy until either: (a) the edge proxy is restarted, or (b) that specific app's cache is refreshed by another `resolveApp()` call. This violates the "immediate revocation" guarantee claimed in the traceability matrix (FR-010).

**Fix:** During `resolveApp()`, explicitly call `accessManager.revokeShare()` for all shares returned with `status !== 'active'`. Additionally, on revocation API calls, push an invalidation event to the edge proxy.

---

### SEC-008 — HIGH: Edge Proxy Uses Hardcoded Mock Token to Call Control Plane

**File:** [`services/edge-proxy/src/index.ts:155-157`](file:///e:/Cloud/capsule-platform/services/edge-proxy/src/index.ts#L155-L157)

```typescript
const res = await fetch(`${controlPlaneUrl}/v1/apps/${appKey}`, {
  headers: { Authorization: "Bearer mock-alice-token" }, // ← HARDCODED
});
```

**Impact:** The edge proxy uses a hardcoded string `'Bearer mock-alice-token'` to authenticate to the control plane. In production this token would need to be a real service credential. If this code path is deployed to production as-is, it would fail to authenticate (best case) or authenticate as "alice" if the mock OIDC provider is still active (worst case — full owner access from the edge proxy to all API endpoints).

**Fix:** The edge proxy must use a proper machine-to-machine service credential (e.g. a scoped publish token with platform-internal role) injected via environment variable at startup.

---

### SEC-009 — HIGH: OIDC Org Provisioned from Claim — Org Takeover Risk

**File:** [`services/control-plane/src/auth/dependencies.py:155-161`](file:///e:/Cloud/capsule-platform/services/control-plane/src/auth/dependencies.py#L155-L161)

```python
org_slug = claims.get("org_slug", "acme")
org = await org_dal.get_by_slug(org_slug)
if not org:
    org = await org_dal.create(slug=org_slug, ...)
```

**Impact:** The organization slug is taken directly from the JWT claim `org_slug`. An attacker who can issue a token with `"org_slug": "acme"` (or any existing org's slug) will be provisioned into that organization as a new user with `platform_role` from their claims. If the real "acme" org has `enforce_sso=False`, this allows arbitrary users to join an existing organization.

**Fix:** Org provisioning from OIDC claims should only happen via verified domain binding (the `DomainVerification` table). New orgs should require an explicit registration flow, not auto-creation on first login.

---

### SEC-010 — MEDIUM: Rollback Race — No DB-Level Lock

**File:** [`services/control-plane/src/api/apps.py`](file:///e:/Cloud/capsule-platform/services/control-plane/src/api/apps.py) — rollback endpoint

**Impact:** Two concurrent rollback requests for the same app can both read the current version, both take pre-rollback snapshots, and both attempt to update `app.current_version_id`. Without a `SELECT ... FOR UPDATE` row lock, the second rollback will silently overwrite the first, leaving the app in an inconsistent version state. The pre-rollback snapshot from the first attempt is then orphaned.

**Fix:** Add `SELECT ... FOR UPDATE SKIP LOCKED` on the app row before any rollback operation. Return 409 Conflict if the app is already being rolled back.

---

### SEC-011 — MEDIUM: Share by Email Creates Users Across Org Without Verification

**File:** [`services/control-plane/src/api/shares.py:186-196`](file:///e:/Cloud/capsule-platform/services/control-plane/src/api/shares.py#L186-L196)

```python
target_user = await user_dal.get_by_email(payload.user_email)
if target_user:
    target_user_id = target_user.id
else:
    target_user = await user_dal.create(email=payload.user_email, ...)
    await user_dal.add_to_org(organization_id=current_user.organization_id, ...)
```

**Impact:** Any `editor` or `owner` can pre-provision a user account for any email address and add them to the organization — without the target user's consent or any verification that the email address belongs to the intended person. An attacker who controls an editor account can populate the organization with arbitrary external user stubs, creating accounts for addresses that may later be claimed by real users who inherit the pre-existing shares.

**Fix:** For non-existent users, send an invitation email instead of auto-creating the account. The invitation flow should require the target to accept before the share activates.

---

### SEC-012 — MEDIUM: NODE_ENV=development Bypasses All Identity Verification

**File:** [`packages/sdk/src/identity.ts:114-121`](file:///e:/Cloud/capsule-platform/packages/sdk/src/identity.ts#L114-L121)

```typescript
const isEmulator =
  process.env.CAPSULE_EMULATOR === 'true' ||
  process.env.NODE_ENV === 'development';   // ← too broad

if (!token) {
  if (isEmulator) {
    return getEmulatorIdentity();  // ← Full access as dev-user-001
  }
```

**Impact:** If `NODE_ENV=development` is set in the sandbox environment (e.g. accidentally in staging, or by a capsule app that sets it), any unauthenticated request receives a fully privileged emulator identity (`org_id: dev-org-001`, roles: `employee/manager/hr`). The gVisor driver explicitly sets `NODE_ENV=production` (line 142), but `DockerDevDriver` may not, and staging environments may omit this flag.

**Fix:** Remove the `NODE_ENV === 'development'` check from the emulator path. Only `CAPSULE_EMULATOR === 'true'` should trigger emulator mode, and this env var must not be set in staging or production. Gate the emulator path on build-time flag, not a runtime environment check.

---

### SEC-013 — MEDIUM: CSP `unsafe-inline` Applied to Capsule App Responses

**File:** [`services/edge-proxy/src/index.ts:58-60`](file:///e:/Cloud/capsule-platform/services/edge-proxy/src/index.ts#L58-L60)

```typescript
res.setHeader(
  "Content-Security-Policy",
  "default-src 'self'; script-src 'self' 'unsafe-inline'; ...",
);
```

**Impact:** `unsafe-inline` in `script-src` allows inline JavaScript in every capsule app response. This weakens XSS protection significantly — if any capsule app renders user-controlled data without escaping, an attacker can execute arbitrary JavaScript. The per-origin isolation (each capsule on its own subdomain) contains the blast radius to one org's data, but the risk is still material for a multi-tenant platform.

**Fix:** Remove `'unsafe-inline'` from the default CSP. Capsule apps that require inline scripts should add a `nonce`-based policy. The platform should consider adding a `Content-Security-Policy-Report-Only` header for monitoring.

---

### SEC-014 — LOW: Audit Log Retains Connector Payload Hash

**File:** [`services/control-plane/src/api/connectors.py:392-420`](file:///e:/Cloud/capsule-platform/services/control-plane/src/api/connectors.py#L392-L420)

**Impact:** The audit event metadata includes `masked_payload` (output of `mask_sensitive_data()`). While the masking function attempts to redact secrets, heuristic masking is explicitly documented as best-effort. If a connector payload contains a secret in an unusual format, it may appear in the audit log.

**Fix:** Do not log any payload content in connector invocation audit events. Log only the connector name, outcome, and app/user context.

---

### SEC-015 — LOW: gVisor ptrace Platform in Tests — Not KVM

**File:** [`packages/sandbox-driver/src/drivers/gvisor.ts:45`](file:///e:/Cloud/capsule-platform/packages/sandbox-driver/src/drivers/gvisor.ts#L45)

```typescript
this.platform = options.platform || process.env.GVISOR_PLATFORM || "ptrace";
```

**Impact:** The default gVisor platform is `ptrace`, which uses software emulation of kernel system calls. This is slower (p95 cold start: 1400ms vs 295ms for KVM) and provides weaker isolation than the `kvm` hardware virtualization backend. Tests run with `ptrace` even on KVM-capable hardware unless `GVISOR_PLATFORM=kvm` is explicitly set. The CI red-team suite passes with `ptrace` — some kernel-level exploit attempts that `ptrace` blocks may behave differently under `kvm`.

**Fix:** Production deployments MUST set `GVISOR_PLATFORM=kvm`. Document this as a required production configuration item in the RUNBOOK. Add a startup check that logs a `WARNING` if `ptrace` is used in production.

---

## Red-Team Test Suite Assessment

**Tests run:** `npm run test:redteam` — 25/25 pass.

**Coverage assessment:**

| Attack Surface                     | Test Coverage     | Gap     |
| ---------------------------------- | ----------------- | ------- |
| Cloud metadata (169.254.169.254)   | ✅ Covered        | None    |
| Private IP ranges (RFC 1918)       | ✅ Covered        | None    |
| DNS rebinding                      | ✅ Covered        | None    |
| Cross-capsule file read            | ✅ Covered        | None    |
| Secret env var exposure            | ✅ Covered        | None    |
| Cookie theft across origins        | ✅ Covered        | None    |
| Resource limits (fork bomb)        | ✅ Covered        | None    |
| Rootfs write (read-only mount)     | ✅ Covered        | None    |
| Identity forgery (signed)          | ✅ Covered        | None    |
| **Raw JSON identity bypass**       | ❌ **NOT TESTED** | SEC-001 |
| **Cross-app egress impersonation** | ❌ **NOT TESTED** | SEC-006 |
| **Connector signature bypass**     | ❌ **NOT TESTED** | SEC-003 |
| Capability escalation              | ✅ Covered        | None    |
| Undeclared capability use          | ✅ Covered        | None    |

**Three critical attack vectors are not covered by existing red-team tests.** Tests should be added for SEC-001, SEC-003, and SEC-006 before pilot.

---

## Production vs. Development Code Paths

The following code paths are known to be development-only and MUST NOT be active in production:

| Component                       | Dev-only Code Path                | Production Guard                           |
| ------------------------------- | --------------------------------- | ------------------------------------------ |
| `DockerDevDriver`               | Shared-kernel sandbox (no gVisor) | Production startup guard ✅                |
| Mock OIDC provider              | `AUTH_PROVIDER=mock`              | Must set `AUTH_PROVIDER=google` or OIDC ✅ |
| Emulator identity               | `CAPSULE_EMULATOR=true`           | Must not be set in production ✅           |
| `NODE_ENV=development` emulator | See SEC-012                       | ⚠️ Fix required                            |
| Edge proxy mock token           | `'Bearer mock-alice-token'`       | ❌ Fix required (SEC-008)                  |
| Raw JSON identity               | SDK line 132                      | ❌ Fix required (SEC-001)                  |

---

## Threat Model — Path from Application Code to Control Plane

The following paths exist from capsule application code to the control plane:

1. **Egress proxy** → connector broker (`POST /connectors/{name}/invoke`): Authenticated by `x-capsule-key`. Vulnerable to SEC-006 (key impersonation). Connector invocations are the _intended_ path; the risk is the identity attached.

2. **Egress proxy** → arbitrary HTTP: Blocked by default-deny allowlist. SSRF protection in place. **Currently no path unless declared in manifest.**

3. **Env var `CAPSULE_IDENTITY_SECRET`** → SDK `createIdentityToken()` → `x-capsule-identity` header forgery: Exploitable via SEC-002. A malicious capsule with the secret can produce valid-looking identity tokens and call connectors or APIs with impersonated identities.

4. **Network `--network none` + egress proxy routing**: Capsule cannot reach the control plane's internal port 8000 directly. The only permitted outbound channel is through the egress proxy. ✅ This is the primary mitigation.

5. **Docker socket mount on builder**: The builder service has the Docker socket mounted (needed to launch gVisor containers). A compromised builder could launch arbitrary containers. This is a privileged component and must be isolated from untrusted input.

---

## Priority Order for Fixes

Before any real-user pilot:

1. **SEC-002** — Remove `CAPSULE_IDENTITY_SECRET` from sandbox env; switch to asymmetric signing
2. **SEC-001** — Remove raw JSON identity bypass
3. **SEC-003** — Remove `verify_signature: False` connector identity fallback
4. **SEC-004** — Fix CORS configuration on control plane
5. **SEC-008** — Replace hardcoded mock token in edge proxy
6. **SEC-007** — Fix share revocation cache eviction in edge proxy
7. **SEC-009** — Require explicit org join flow; don't auto-provision from OIDC slug claim
8. **SEC-005** — Resolve platform_role from DB, not JWT claims
9. **SEC-011** — Replace auto-create user with invitation flow
10. **SEC-012** — Remove `NODE_ENV=development` from emulator bypass
