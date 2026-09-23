# Security Findings & Red-Team Assessment (Prompt 16)

**Assessment Date**: 2026-09-21  
**Target**: Software Capsule Platform (Phase 1)  
**Assessor**: Security Red-Team Test Suite  
**Scope**: 9 Primary Attack Surfaces across Sandbox, Edge Proxy, Egress Proxy, Credential Broker, and Control Plane.

---

## Executive Summary

An automated red-team security assessment was conducted against the Software Capsule Platform to evaluate the effectiveness of its security boundaries, sandboxing, network isolation, credential broker, and capability enforcement.

A deliberately malicious test application (`examples/malicious-app`) and an automated test suite (`tests/redteam/redteam.test.ts`) were executed to simulate adversarial attacks across all 9 required attack vectors.

### Phase 1 Acceptance Criterion

> **Status**: **PASSED**  
> All 9 active attack vectors are successfully blocked by platform security controls. Zero attacks bypassed enforcement in the automated suite.

---

## Attack Surface Assessment Matrix

| #     | Attack Surface              | Target / Objective                                                                           | Defense Mechanism                                                                                                                                                                                                                                                          | Test Status |
| ----- | --------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| **1** | **Network Egress**          | Reach internet, internal IPs (RFC 1918), and Cloud Metadata (`169.254.169.254`)              | Egress proxy default-deny, connection-time SSRF/DNS rebinding defense, container `--network none`                                                                                                                                                                          | **BLOCKED** |
| **2** | **Cross-Capsule Data**      | Read another capsule's SQLite database or blob files via path traversal (`../`)              | Per-capsule isolated host volumes, `@capsule/sdk` path traversal defense (`FileStorageError`)                                                                                                                                                                              | **BLOCKED** |
| **3** | **Secret Discovery**        | Read platform master secrets or connector tokens from environment or files                   | Zero-secret injection into container env, AES-256-GCM encryption at rest, masked logging                                                                                                                                                                                   | **BLOCKED** |
| **4** | **Session / Cookie Theft**  | Steal cookies across origins or from the dashboard                                           | `HttpOnly`, `SameSite=Lax`, domain separation (`*.apps.localhost` vs `dashboard.localhost`)                                                                                                                                                                                | **BLOCKED** |
| **5** | **Resource Quotas**         | Exceed CPU, memory, disk quota, or request timeout                                           | Container cgroup limits (`--memory 256m`, `--cpus 0.5`), SQLite `PRAGMA max_page_count` (`SQLITE_FULL`), edge proxy timeouts                                                                                                                                               | **BLOCKED** |
| **6** | **Sandbox Escape**          | Write outside allowed paths, use raw sockets, fork bomb, or exploit host kernel              | `GVisorDriver` user-space kernel (Sentry Go syscall implementation, no shared kernel with host), read-only rootfs (`--read-only`, `/app:ro`), non-root (`1000:1000`), `--cap-drop=ALL`, `no-new-privileges`, `--pids-limit 64`, `--network none`, Production Startup Guard | **BLOCKED** |
| **7** | **Identity Header Forgery** | Forge HMAC signature, use `alg: none`, replay expired tokens, or cross-app audience mismatch | HMAC-SHA256 signature verification, `alg` whitelist, timestamp expiry check, `aud` matching in `@capsule/sdk`                                                                                                                                                              | **BLOCKED** |
| **8** | **Undeclared Capabilities** | Invoke undeclared connectors or unauthorized AI capabilities                                 | Control-plane capability verification before broker invocation (`403 CAPABILITY_DENIED`)                                                                                                                                                                                   | **BLOCKED** |
| **9** | **Unauthorized Escalation** | Add capabilities in update without owner approval                                            | Capability escalation engine (`detect_capability_escalation`), scoped publish token self-approval block (`403 FORBIDDEN`)                                                                                                                                                  | **BLOCKED** |

---

## Detailed Findings & Hardening Recommendations

### Finding SEC-001: Development Container Driver (`DockerDevDriver`) Boundary Limitations

- **Severity**: **RESOLVED / CLOSED** (Previously MEDIUM Architecture Caveat)
- **Component**: `packages/sandbox-driver/src/drivers/gvisor.ts` & `docker.ts`
- **Resolution (Prompt 21B)**:
  1. **Production GVisorDriver (Option A)**: Implemented in `packages/sandbox-driver/src/drivers/gvisor.ts` using gVisor's `runsc` runtime. The Sentry architecture intercepts and handles all Linux system calls in user-space Go, preventing untrusted guest code from ever executing host kernel code or accessing host namespaces.
  2. **Production Startup Guard**: Implemented in `DockerDevDriver` (`packages/sandbox-driver/src/drivers/docker.ts`). If `NODE_ENV === 'production'`, `DockerDevDriver` strictly **refuses to initialize**, throwing a `[SECURITY INVARIANT VIOLATION]` error unless explicitly overridden with `ALLOW_INSECURE_DEV_DRIVER=true` (which logs an urgent multi-line warning banner).
  3. **Driver Conformance Suite**: Added `packages/sandbox-driver/tests/driver_conformance.test.ts` running 43 tests across both drivers covering interface contracts, security flags, lifecycle transitions, cold-start latency measurements, and startup guards.
  4. **Red-Team Suite Validation**: Re-executed `tests/redteam/redteam.test.ts` verifying that sandbox escape, raw sockets, process exhaustion, and unauthorized container drivers are completely blocked. All 25 tests pass.

---

### Finding SEC-002: Default Signing Key in Local Emulator Mode

- **Severity**: **LOW** (Hardening)
- **Component**: `packages/sdk/src/identity.ts`
- **Description**:  
  In local emulator mode (`CAPSULE_EMULATOR=true`), `@capsule/sdk` falls back to a hardcoded development signing secret (`dev-emulator-secret-key-1234567890`) when `CAPSULE_IDENTITY_SECRET` is not provided. If a production container is misconfigured with `CAPSULE_EMULATOR=true`, an attacker could forge identity tokens signed with the well-known development key.
- **Impact**:  
  Authentication bypass if a production capsule accidentally runs in emulator mode.
- **Suggested Fix**:  
  Enforce that in production containers (`NODE_ENV=production`), `isEmulatorMode()` unconditionally returns `false`, and `getIdentity()` refuses to use fallback keys, strictly throwing `NO_SECRET_CONFIGURED` if `CAPSULE_IDENTITY_SECRET` is absent.

---

### Finding SEC-003: Key Rotation Automation for Encrypted Credentials

- **Severity**: **INFORMATIONAL** (Operational Hardening)
- **Component**: `services/control-plane/src/crypto.py` & `services/control-plane/src/db/models.py`
- **Description**:  
  The `connector_credentials` table stores encrypted secrets using AES-256-GCM tagged with `key_id: "v1"`. There is currently no automated CLI or control-plane command to rotate the master key (`CAPSULE_SECRET_KEY`) from `v1` to `v2` and re-encrypt existing records.
- **Impact**:  
  In the event of a suspected master key compromise, operators must manually migrate database records.
- **Suggested Fix**:  
  Add an admin endpoint or CLI command `capsule secrets rotate --old-key <k1> --new-key <k2>` that iterates over `connector_credentials`, decrypts with `v1`, re-encrypts with `v2`, and updates `key_id` atomically.

---

### Finding SEC-004: Public-Facing Edge Proxy Mounted Host Docker Socket (Root-Equivalent Host Takeover Risk)

- **Severity**: **CRITICAL** (CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H — Base Score: 9.8)
- **Date Discovered**: 2026-09-23
- **Status**: **RESOLVED / CLOSED** (Fix Commits: [`0392158`](https://github.com/lakshmikanth823/agent-capsule-platform/commit/0392158), [`eba1bd1`](https://github.com/lakshmikanth823/agent-capsule-platform/commit/eba1bd1))
- **Component**: `services/edge-proxy/Dockerfile`, `deploy/compose/docker-compose.control-plane.yml`
- **Description & Root Cause**:  
  In earlier iterations, `services/edge-proxy/Dockerfile` installed `docker.io`, added user `capsule` to the host `docker` group, and mounted `/var/run/docker.sock` into the container so the proxy could locally manage sandbox lifecycles.
  Because `edge-proxy` directly faces the public internet (handling incoming HTTPS requests, ticket exchanges, and subdomain routing), exposing `/var/run/docker.sock` created a critical security flaw: any RCE vulnerability in `edge-proxy` would grant the attacker root-equivalent access to the control-plane host. An attacker could issue Docker API commands to mount the host root filesystem (`docker run -v /:/host`), exfiltrate database credentials, or compromise the control plane. Additionally, `runsc` was only provisioned on the dedicated `sandbox-host`, meaning sandboxes launched by the control-plane host could not run under gVisor.
- **Remediation**:
  1. **Complete Removal of Docker Socket**: Removed `/var/run/docker.sock` and `docker.io` from `services/edge-proxy`. The proxy runs as an unprivileged network process with zero Docker privileges.
  2. **Dedicated Private Sandbox Runner**: Created `services/sandbox-runner` deployed exclusively on the private `sandbox-host` runner where `runsc` is installed.
  3. **Authenticated Private RPC**: Built `RemoteSandboxDriver` which calls `sandbox-runner` over internal VPC LAN on TCP port 8095 using bearer token authentication (`RUNNER_SHARED_SECRET`), with secrets dynamically retrieved from AWS Secrets Manager via `entrypoint-node.sh`.
  4. **Strict Firewall Isolation**: Port 8095 is restricted to private VPC CIDRs (`10.0.0.0/8`, `172.16.0.0/12`) via UFW firewall rules and application-layer validation, dropping all external traffic.

---

## Test Execution Details

### Automated Test Output

- **Vitest Red-Team Suite (`tests/redteam/redteam.test.ts`)**: **25/25 tests passed (100%)**
- **Vitest Driver Conformance Suite (`packages/sandbox-driver/tests/driver_conformance.test.ts`)**: **43/43 tests passed (100%)**
- **Pytest Security Suite (`test_capabilities_escalation.py`, `test_credential_broker.py`, `test_cross_user_access.py`, `test_constraints.py`)**: **16/16 tests passed (100%)**
- **Total Monorepo Tests**: **188+ tests passing across all suites**
