# Threat Model — Capsule Platform

**Version:** 1.0 (Pre-Pilot)  
**Date:** 2026-09-22  
**Based On:** Independent code audit (Prompt 27), red-team suite results, architecture review of TRD.md  
**Methodology:** STRIDE

---

## 1. System Overview

The Capsule Platform is a multi-tenant application platform. The primary attack surfaces are:

```
[User Browser] ──HTTPS──► [nginx Edge Proxy]
                                │
                    ┌───────────┼───────────────┐
                    │           │               │
              [Dashboard]  [App Subdomain]  [Control Plane API]
                                │
                          [Edge Proxy]
                                │
                    ┌───────────┴───────────┐
               [Sandbox Container]    [Egress Proxy]
               (gVisor / runsc)             │
                    │                  [External APIs]
               [SQLite DB]          [LLM Providers]
               [File Blobs]         [Connectors]
```

**Trust Boundaries:**
1. Internet → nginx Edge (public)
2. nginx Edge → Control Plane (internal, VPC-only)
3. Edge Proxy → Sandbox Containers (localhost/Docker network)
4. Sandbox Containers → Egress Proxy (localhost)
5. Egress Proxy → External Internet (allowlist-gated)
6. Control Plane → AWS Services (IAM-controlled)

**Actors and Trust Levels:**

| Actor | Trust Level | Notes |
|---|---|---|
| Platform operator | Full trust | Manages infrastructure, secrets, kill switch |
| Org admin (owner role) | High — within their org | Can manage all apps, users, profiles |
| Org editor | Medium | Can publish, share, manage capsules |
| Org user | Low | Can use apps they have access to |
| Capsule application code | Untrusted | Runs in gVisor sandbox; output is untrusted data |
| External API providers (OpenAI, Google) | Untrusted external | Results treated as untrusted data |

---

## 2. Threat Analysis (STRIDE)

### S — Spoofing

| ID | Threat | Component | Current Mitigation | Residual Risk |
|---|---|---|---|---|
| S-01 | Capsule app forges `x-capsule-identity` header with raw JSON | SDK identity verification | Edge proxy adds header after request; gVisor sets `NODE_ENV=production` | **HIGH** — SEC-001: raw JSON bypass exists in SDK. Fix required. |
| S-02 | Capsule app forges identity by reading `CAPSULE_IDENTITY_SECRET` | gVisor driver env injection | gVisor kernel isolation prevents host-level escalation | **CRITICAL** — SEC-002: signing secret injected into container env. Any `process.env.CAPSULE_IDENTITY_SECRET` read exposes it. Fix required. |
| S-03 | Attacker crafts token with `platform_role: "owner"` using mock OIDC | MockOIDCProvider | MockOIDCProvider must not run in production; real OIDC enforces claim origin | **MEDIUM** — SEC-005. Residual: if `AUTH_PROVIDER=mock` accidentally set in production. |
| S-04 | Cross-capsule egress: malicious app uses another app's egress allowlist | Egress proxy app-key extraction | Headers are app-side-provided; no cryptographic binding | **HIGH** — SEC-006. Residual until vsock/mTLS app identity binding is implemented. |
| S-05 | User spoofs org membership via `org_slug` OIDC claim | Auth dependency org provisioning | SSO enforcement per domain partially mitigates | **HIGH** — SEC-009. Residual for orgs without SSO enforcement. |

### T — Tampering

| ID | Threat | Component | Current Mitigation | Residual Risk |
|---|---|---|---|---|
| T-01 | Capsule writes outside its `/data` volume | gVisor read-only rootfs | `--read-only` flag, tmpfs for /tmp only | **LOW** — Verified by red-team test. gVisor Gofer enforces mount points. |
| T-02 | Concurrent rollback corrupts app version state | Rollback endpoint | No DB-level row lock on app during rollback | **MEDIUM** — SEC-010. Unlikely in single-tenant pilot, higher risk at scale. |
| T-03 | Audit log tampered post-write | PostgreSQL | PL/pgSQL trigger blocks UPDATE/unauthorized DELETE | **LOW** — SHA-256 hash chain verified by `capsule audit verify`. |
| T-04 | Capsule modifies another capsule's SQLite file | Volume mounts | Each capsule gets its own data directory; paths not shared | **LOW** — Verified by red-team (cross-capsule filesystem isolation test). |

### R — Repudiation

| ID | Threat | Component | Current Mitigation | Residual Risk |
|---|---|---|---|---|
| R-01 | Actor denies publishing a version | Audit log | Every publish logged with actor_user_id, timestamp, SHA-256 chain | **LOW** — Cryptographic chain prevents log deletion. |
| R-02 | Actor denies revoking a share | Audit log | Share revocation logged | **LOW** |
| R-03 | Actor denies LLM invocation | AI gateway usage records | Token counts, model, actor logged per invocation | **LOW** — Content not stored by default; metadata undeniable. |

### I — Information Disclosure

| ID | Threat | Component | Current Mitigation | Residual Risk |
|---|---|---|---|---|
| I-01 | Capsule reads another capsule's SQLite data | File isolation | Per-app data directories, no shared paths | **LOW** — Verified by red-team test. |
| I-02 | Capsule reads environment variables containing secrets | Env var isolation | No raw secrets injected (except SEC-002 signing key) | **HIGH** — SEC-002. The signing secret is in env. Platform and connector credentials are NOT in env. |
| I-03 | LLM prompt/response content stored and accessed by operator | AI gateway privacy logging | Content logging OFF by default; opt-in only | **LOW** — Platform operator can enable content logging org-by-org. Documented to users. |
| I-04 | Connector OAuth tokens retrieved via API response | Connector credential API | Credentials never returned in API responses; encrypted at rest | **LOW** — Verified by test `test_secret_encryption_and_zero_leakage`. |
| I-05 | Cross-origin cookie theft | Edge proxy origin isolation | Host-only cookies (no `Domain` attribute); per-subdomain isolation | **LOW** — Verified by red-team test. |
| I-06 | Audit log contains connector payload data | Audit DAL | `mask_sensitive_data()` applied; but best-effort | **LOW** — SEC-014. Residual if unusual secret format bypasses heuristic. |
| I-07 | Session token in access logs | nginx / uvicorn logging | Structured JSON logging; no Authorization header logged by default | **LOW** — Not tested for staging nginx; operator must verify log format. |

### D — Denial of Service

| ID | Threat | Component | Current Mitigation | Residual Risk |
|---|---|---|---|---|
| D-01 | Fork bomb exhausts host processes | gVisor pids-limit | `--pids-limit 64` enforced; verified by red-team | **LOW** — Limit enforced at container level. |
| D-02 | CPU/memory exhaustion | gVisor cgroups | `--cpus`, `--memory`, `--memory-swap` enforced | **LOW** — cgroups v2 enforced. |
| D-03 | Disk exhaustion via SQLite writes | SQLite `max_page_count` | `PRAGMA max_page_count` set; verified by red-team | **LOW** |
| D-04 | Egress bandwidth exhaustion | Egress proxy byte quota | 100 MB/day limit per app; tracked in-memory | **MEDIUM** — Daily counter is in-memory and resets on restart; not persisted to DB. |
| D-05 | Rate limiting at edge (DoS from internet) | nginx rate limiting | 100r/m API, 500r/m app, 10r/m login zones configured | **LOW** — Edge nginx rate limits in place. |
| D-06 | AI budget exhaustion by a single app | AI gateway budget hard stop | Monthly budget enforced per app; fail-closed 429 | **LOW** — Hard stop verified by test. |

### E — Elevation of Privilege

| ID | Threat | Component | Current Mitigation | Residual Risk |
|---|---|---|---|---|
| E-01 | Capsule escapes gVisor to host kernel | gVisor Sentry | Sentry handles all syscalls in user space; no host kernel access | **LOW** — Verified by red-team (rootfs write blocked, /etc/shadow blocked). |
| E-02 | Capsule escalates from `user` role to `owner` | Shares + role enforcement | `check_management_permission()` enforces role; User role blocked at API | **LOW** — Verified by test `test_share_flow_and_role_enforcement`. |
| E-03 | Publish token approves its own capability escalation | Capability escalation engine | Scoped publish tokens explicitly blocked from self-approving escalations | **LOW** — Verified by test `test_capability_escalation_lifecycle`. |
| E-04 | Attacker gains `owner` via org_slug claim | Auth provisioning | See S-05 / SEC-009 | **HIGH** — Residual until org join flow is secured. |
| E-05 | Capsule app gains admin access via forged identity | Identity verification | Multiple layers (edge proxy signs, SDK verifies); SEC-001/002 bypass paths exist | **CRITICAL** — Two unfixed bypass paths (SEC-001, SEC-002). |

---

## 3. Residual Risks Summary

> [!CAUTION]
> The following residual risks must be explicitly accepted by the platform owner before pilot launch.

| Risk ID | Severity | Description | Acceptance Condition |
|---|---|---|---|
| RR-01 | **CRITICAL** | Identity signing key in sandbox env (SEC-002) — capsule can forge any identity | Fix before real-user pilot OR accept by restricting pilot to internal apps with no sensitive data |
| RR-02 | **CRITICAL** | CORS wildcard on control plane (SEC-004) — CSRF vector for all admin APIs | Fix before browser-accessible deployment |
| RR-03 | **CRITICAL** | Connector identity signature bypass fallback (SEC-003) | Fix before enabling connectors in pilot |
| RR-04 | **HIGH** | Share revocation not instantly reflected in edge proxy (SEC-007) | Accept with mitigation: immediate edge proxy restart after bulk revocations |
| RR-05 | **HIGH** | App key unverified in egress proxy (SEC-006) | Accept for pilot with low-sensitivity apps; fix before GA |
| RR-06 | **HIGH** | Org auto-provisioning from OIDC claim (SEC-009) | Mitigate: enforce SSO for all pilot org domains |
| RR-07 | **MEDIUM** | gVisor ptrace platform in test/staging (slower cold start, slightly weaker isolation) | Accept for pilot; production MUST use `GVISOR_PLATFORM=kvm` |
| RR-08 | **MEDIUM** | No eTLD+1 domain isolation check in edge proxy (GAP-003) | Accept with mitigation: use separate DNS zones as documented |
| RR-09 | **LOW** | Egress byte quota counter is in-memory, not persisted (D-04) | Accept for pilot; persistent quota tracking is a GA item |

---

## 4. Security Controls Already Verified

The following controls are confirmed effective by independent test:

| Control | Test | Verified |
|---|---|---|
| gVisor read-only rootfs | `redteam.test.ts > 6. Sandbox Escape` | ✅ |
| `--pids-limit 64` (fork bomb) | `redteam.test.ts > fork bomb` | ✅ |
| Cloud metadata block (169.254.169.254) | `redteam.test.ts > 1. SSRF` | ✅ |
| RFC 1918 egress block | `egress.test.ts > should block private IP` | ✅ |
| DNS rebinding protection | `egress.test.ts > DNS rebinding` | ✅ |
| Cross-capsule filesystem isolation | `redteam.test.ts > 2. Cross-Capsule Data` | ✅ |
| Secret zero-leakage in audit log | `test_credential_broker.py > test_audit_logging_no_secrets` | ✅ |
| Capability escalation self-approval block | `test_capabilities_escalation.py` | ✅ |
| Org-level session revocation | `test_sso_and_scim.py > deprovisioning` | ✅ |
| Budget hard stop (AI) | `test_ai_gateway.py > BUDGET_EXCEEDED` | ✅ |
| Audit log tamper-evidence | `test_audit_system.py > all 8 scenarios` | ✅ |
| Cookie origin isolation | `redteam.test.ts > 4. Cookie Isolation` | ✅ |

---

## 5. Recommended Next-Step Mitigations (Priority Order)

1. **Switch identity signing to RS256/Ed25519** (fixes SEC-001, SEC-002) — eliminates the two CRITICAL paths
2. **Fix CORS on control plane** (fixes SEC-004) — eliminates CSRF risk
3. **Remove connector identity signature bypass** (fixes SEC-003) — eliminates impersonation in connector calls
4. **Add event-driven share invalidation** to edge proxy (fixes SEC-007) — makes revocation truly instant
5. **Replace hardcoded mock token** in edge proxy with a real service credential (fixes SEC-008)
6. **Require explicit org join flow** instead of OIDC slug auto-provisioning (fixes SEC-009)
7. **Add red-team tests for SEC-001, SEC-003, SEC-006** to prevent regression
8. **Persist egress byte quota counters** to database (fixes D-04)
