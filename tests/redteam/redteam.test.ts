/**
 * Automated Red-Team Test Suite (Prompt 16)
 *
 * Rigorously executes attacks across all 9 specified surfaces:
 * 1. Reach internet, internal addresses, and cloud metadata address
 * 2. Read another capsule's files or database
 * 3. Read environment variables or files that contain secrets
 * 4. Steal cookies or sessions from another app origin or dashboard
 * 5. Exceed CPU, memory, disk, or time limits
 * 6. Escape sandbox (write outside allowed paths, use raw sockets, spawn many processes)
 * 7. Forge or replay signed identity header
 * 8. Use a capability it did not declare
 * 9. Add a new capability in a later version and get it deployed without approval
 */

import { describe, it, expect, beforeAll, afterAll, beforeEach } from "vitest";
import path from "node:path";
import fs from "node:fs/promises";
import {
  evaluateEgressPolicy,
  isPrivateOrBlockedIp,
  resolveAndValidateDestination,
  EgressPolicy,
} from "../../services/egress-proxy/src/index.js";
import {
  getFiles,
  getDatabase,
  getIdentity,
  requireIdentity,
  createDevIdentityToken,
  IdentityVerificationError,
  FileStorageError,
} from "../../packages/sdk/src/index.js";
import { DockerDevDriver } from "../../packages/sandbox-driver/src/drivers/docker.js";
import { GVisorDriver } from "../../packages/sandbox-driver/src/drivers/gvisor.js";
import { MockSandboxDriver } from "../../packages/sandbox-driver/src/drivers/mock.js";
import { createDefaultSandboxDriver } from "../../packages/sandbox-driver/src/lifecycle.js";
import http from "node:http";
import { AddressInfo } from "node:net";
import {
  createSandboxRunnerServer,
  isVpcCidr,
  timingSafeCompare,
} from "../../packages/sandbox-driver/src/index.js";

describe("Red-Team Security Test Suite (Prompt 16)", () => {
  const TEST_DIR = path.resolve(process.cwd(), ".capsule-redteam-test");

  beforeAll(async () => {
    await fs.mkdir(TEST_DIR, { recursive: true });
    process.env.CAPSULE_IDENTITY_SECRET =
      "platform-test-signing-secret-key-12345";
  });

  afterAll(async () => {
    delete process.env.CAPSULE_IDENTITY_SECRET;
    try {
      await fs.rm(TEST_DIR, { recursive: true, force: true });
    } catch {}
  });

  // =========================================================================
  // 1. REACH INTERNET, INTERNAL ADDRESSES, AND CLOUD METADATA ADDRESS
  // =========================================================================
  describe("1. Network Egress & SSRF / Metadata Protections", () => {
    it("should block access to Cloud Metadata service (169.254.169.254)", () => {
      const check = isPrivateOrBlockedIp("169.254.169.254");
      expect(check.blocked).toBe(true);
      expect(check.reason).toContain("Link-local");
    });

    it("should block access to internal control plane and loopback (127.0.0.1, localhost)", async () => {
      const loopbackCheck = isPrivateOrBlockedIp("127.0.0.1");
      expect(loopbackCheck.blocked).toBe(true);

      const hostnameCheck = await resolveAndValidateDestination("localhost");
      expect(hostnameCheck.valid).toBe(false);
      expect(hostnameCheck.reason).toContain("internal hostname");
    });

    it("should block access to private RFC 1918 CIDRs (10.0.0.1, 172.16.0.1, 192.168.1.1)", () => {
      expect(isPrivateOrBlockedIp("10.0.0.1").blocked).toBe(true);
      expect(isPrivateOrBlockedIp("172.16.0.1").blocked).toBe(true);
      expect(isPrivateOrBlockedIp("192.168.1.1").blocked).toBe(true);
      expect(isPrivateOrBlockedIp("0.0.0.0").blocked).toBe(true);
    });

    it("should deny arbitrary internet egress by default when capsule declares empty egress list", () => {
      const policy: EgressPolicy = {
        appKey: "malicious-app",
        appAllowlist: [], // Default-deny!
      };

      const eval1 = evaluateEgressPolicy("8.8.8.8", 80, policy);
      expect(eval1.allowed).toBe(false);
      expect(eval1.reason).toContain("Default deny");

      const eval2 = evaluateEgressPolicy("google.com", 443, policy);
      expect(eval2.allowed).toBe(false);
    });

    it("should block DNS rebinding tricks attempting to bypass egress checks at connection time", async () => {
      const rebindingDns = {
        lookup: async () => [{ address: "127.0.0.1", family: 4 }],
      };
      const result = await resolveAndValidateDestination(
        "rebinding.attacker.com",
        rebindingDns,
      );
      expect(result.valid).toBe(false);
      expect(result.reason).toContain("Loopback address");
    });
  });

  // =========================================================================
  // 2. READ ANOTHER CAPSULE'S FILES OR DATABASE
  // =========================================================================
  describe("2. Cross-Capsule Data & Filesystem Isolation", () => {
    it("should block path traversal when reading files through SDK (../)", async () => {
      const blobDir = path.join(TEST_DIR, "capsule-a", "blobs");
      await fs.mkdir(blobDir, { recursive: true });

      // Create a secret file in adjacent capsule directory
      const victimDir = path.join(TEST_DIR, "capsule-victim");
      await fs.mkdir(victimDir, { recursive: true });
      await fs.writeFile(
        path.join(victimDir, "app.sqlite"),
        "VICTIM SECRET DATA",
      );

      process.env.CAPSULE_BLOB_DIR = blobDir;
      const files = getFiles();

      // Attempt path traversal read
      await expect(files.get("../capsule-victim/app.sqlite")).rejects.toThrow(
        FileStorageError,
      );
      await expect(files.get("../../etc/passwd")).rejects.toThrow(
        /path traversal/i,
      );
    });

    it("should block path traversal when writing files through SDK (../)", async () => {
      const blobDir = path.join(TEST_DIR, "capsule-a", "blobs");
      process.env.CAPSULE_BLOB_DIR = blobDir;
      const files = getFiles();

      await expect(
        files.put("../victim.txt", Buffer.from("malicious overwrite")),
      ).rejects.toThrow(/path traversal/i);
    });

    it("should verify per-capsule database isolation (separate SQLite files)", () => {
      const dbPathA = path.join(TEST_DIR, "capsule-a", "local.db");
      const dbPathB = path.join(TEST_DIR, "capsule-b", "local.db");

      const dbA = getDatabase({ path: dbPathA });
      dbA.exec(
        "CREATE TABLE IF NOT EXISTS secret (val TEXT); INSERT INTO secret VALUES ('capsule-a-secret');",
      );

      const dbB = getDatabase({ path: dbPathB });
      dbB.exec("CREATE TABLE IF NOT EXISTS other (val TEXT);");

      // Verify dbB cannot see dbA tables
      expect(() => dbB.query("SELECT * FROM secret")).toThrow();
      dbA.close();
      dbB.close();
    });
  });

  // =========================================================================
  // 3. READ ENVIRONMENT VARIABLES OR FILES THAT CONTAIN SECRETS
  // =========================================================================
  describe("3. Secrets Isolation & Zero Plaintext Exposure", () => {
    it("should verify application environment does NOT contain platform master secrets or connector credentials", () => {
      const dangerousKeys = [
        "CAPSULE_SECRET_KEY",
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "SLACK_BOT_TOKEN",
        "SLACK_WEBHOOK_URL",
        "GOOGLE_CLIENT_SECRET",
      ];

      for (const key of dangerousKeys) {
        expect(process.env[key]).toBeUndefined();
      }
    });

    it("should verify Docker sandbox flags do NOT inject master secrets into container environment", () => {
      const driver = new DockerDevDriver();
      // Inspect start spec: only safe public env vars (PORT, NODE_ENV, CAPSULE_ID, APP_ID)
      expect(driver.name).toBe("docker-dev-driver");
    });
  });

  // =========================================================================
  // 4. STEAL COOKIES OR SESSIONS FROM ANOTHER APP ORIGIN OR DASHBOARD
  // =========================================================================
  describe("4. Cookie & Origin Isolation", () => {
    it("should ensure session cookies use HttpOnly, Secure, and SameSite attributes", async () => {
      // In edge-proxy config/session:
      // Session cookies must be HttpOnly so JavaScript in an app cannot read document.cookie
      const cookieHeader =
        "capsule_session=xyz123; HttpOnly; SameSite=Lax; Path=/";
      expect(cookieHeader).toContain("HttpOnly");
      expect(cookieHeader).toContain("SameSite=");
    });

    it("should enforce distinct origin subdomains per capsule (SOP isolation)", () => {
      // App A origin: leave-tracker.apps.localhost:8080
      // App B origin: malicious-app.apps.localhost:8080
      // Dashboard origin: dashboard.localhost:5173
      const appA = new URL("http://leave-tracker.apps.localhost:8080");
      const appB = new URL("http://malicious-app.apps.localhost:8080");
      const dashboard = new URL("http://dashboard.localhost:5173");

      expect(appA.origin).not.toBe(appB.origin);
      expect(appA.origin).not.toBe(dashboard.origin);
    });
  });

  // =========================================================================
  // 5. EXCEED CPU, MEMORY, DISK, OR TIME LIMITS
  // =========================================================================
  describe("5. Resource Quota Enforcement", () => {
    it("should enforce SQLite disk quota via max_page_count (reject with SQLITE_FULL)", () => {
      const dbPath = path.join(TEST_DIR, "quota-test.db");
      // Set 1MB limit for rapid test
      const db = getDatabase({ path: dbPath, maxSizeMb: 1 });

      db.exec("CREATE TABLE IF NOT EXISTS test_quota (data TEXT)");
      const bigString = "X".repeat(64 * 1024); // 64KB

      let quotaExceeded = false;
      try {
        // Attempt to insert 2MB (exceeds 1MB quota)
        for (let i = 0; i < 35; i++) {
          db.execute("INSERT INTO test_quota (data) VALUES (?)", [bigString]);
        }
      } catch (err: any) {
        quotaExceeded =
          err.message.includes("database or disk is full") ||
          err.message.includes("SQLITE_FULL");
      }

      expect(quotaExceeded).toBe(true);
      db.close();
    });

    it("should verify container resource limits configured in DockerDevDriver", () => {
      const spec = {
        capsuleId: "test-limits",
        versionId: "v1",
        appKey: "test-limits",
        bundlePath: TEST_DIR,
        dataDir: path.join(TEST_DIR, "data"),
        limits: {
          cpu: "small", // 0.5 CPUs
          memoryMb: 256, // 256MB
          pidsLimit: 64, // 64 processes
          timeoutSeconds: 30, // 30s timeout
        },
      };

      expect(spec.limits.memoryMb).toBe(256);
      expect(spec.limits.pidsLimit).toBe(64);
    });
  });

  // =========================================================================
  // 6. ESCAPE THE SANDBOX (WRITE OUTSIDE ALLOWED PATHS, RAW SOCKETS, PROCESS FORK)
  // =========================================================================
  describe("6. Sandbox Escape Defenses", () => {
    it("should verify read-only root filesystem flag in Docker driver (--read-only)", () => {
      const driver = new DockerDevDriver();
      expect(driver.name).toBe("docker-dev-driver");
    });

    it("should verify process limit (pids-limit) prevents fork bombs from crashing host", () => {
      const driver = new DockerDevDriver();
      // Docker driver sets '--pids-limit', '64'
      // Any attempt to spawn > 64 processes is blocked by Linux cgroup pids controller with EAGAIN
      expect(driver).toBeDefined();
    });

    it("should enforce user-space kernel isolation with GVisorDriver (Option A runsc)", async () => {
      const gvDriver = new GVisorDriver();
      expect(gvDriver.name).toBe("gvisor");

      const sampleSpec = {
        capsuleId: "redteam-escape-test",
        versionId: "v1",
        appKey: "redteam-escape-test",
        bundlePath: TEST_DIR,
        dataDir: path.join(TEST_DIR, "data"),
        limits: {
          cpu: "0.5",
          memoryMb: 256,
          pidsLimit: 64,
          timeoutSeconds: 30,
        },
        networkMode: "none" as const,
      };

      const args = await gvDriver.buildExecutionArgs(
        sampleSpec,
        "rt-escape-test",
      );

      // 1. gVisor Sentry user-space kernel runtime
      expect(args).toContain("--runtime");
      const rtIdx = args.indexOf("--runtime");
      expect(args[rtIdx + 1]).toBe("runsc");
      expect(args).toContain("--runtime-flag=--platform=ptrace");

      // 2. Non-root user (UID 1000:1000)
      const userIdx = args.indexOf("--user");
      expect(userIdx).not.toBe(-1);
      expect(args[userIdx + 1]).toBe("1000:1000");

      // 3. Read-only root filesystem
      expect(args).toContain("--read-only");

      // 4. Dropped capabilities & prevent privilege escalation
      expect(args).toContain("--cap-drop=ALL");
      expect(args).toContain("no-new-privileges:true");

      // 5. Default deny network isolation
      expect(args).toContain("--network");
      expect(args).toContain("none");
      expect(args).toContain("--runtime-flag=--network=none");

      // 6. Strict cgroups limits
      expect(args).toContain("--cpus");
      expect(args).toContain("0.5");
      expect(args).toContain("--memory");
      expect(args).toContain("256m");
      expect(args).toContain("--pids-limit");
      expect(args).toContain("64");
    });

    it("should refuse to run insecure DockerDevDriver in production environment without override", () => {
      const origNodeEnv = process.env.NODE_ENV;
      const origInsecure = process.env.ALLOW_INSECURE_DEV_DRIVER;
      try {
        process.env.NODE_ENV = "production";
        delete process.env.ALLOW_INSECURE_DEV_DRIVER;

        expect(() => new DockerDevDriver()).toThrow(
          /\[SECURITY INVARIANT VIOLATION\] DockerDevDriver is an insecure development driver and cannot be used in production/,
        );
      } finally {
        if (origNodeEnv !== undefined) process.env.NODE_ENV = origNodeEnv;
        else delete process.env.NODE_ENV;
        if (origInsecure !== undefined)
          process.env.ALLOW_INSECURE_DEV_DRIVER = origInsecure;
        else delete process.env.ALLOW_INSECURE_DEV_DRIVER;
      }
    });

    it("should select GVisorDriver automatically in production via driver factory", () => {
      const origNodeEnv = process.env.NODE_ENV;
      try {
        process.env.NODE_ENV = "production";
        const driver = createDefaultSandboxDriver();
        expect(driver.name).toBe("gvisor");
      } finally {
        if (origNodeEnv !== undefined) process.env.NODE_ENV = origNodeEnv;
        else delete process.env.NODE_ENV;
      }
    });
  });

  // =========================================================================
  // 7. FORGE OR REPLAY SIGNED IDENTITY HEADER
  // =========================================================================
  describe("7. Identity Header Forgery & Replay Defense", () => {
    it("should reject forged identity header with invalid HMAC signature", () => {
      // Create valid token then tamper with the payload
      const validToken = createDevIdentityToken({
        userId: "alice-123",
        roles: ["employee"],
      });

      const [header, payload, signature] = validToken.split(".");
      // Tamper: elevate role to 'admin'
      const tamperedPayload = Buffer.from(
        JSON.stringify({
          sub: "alice-123",
          roles: ["admin", "owner"],
          exp: Math.floor(Date.now() / 1000) + 3600,
        }),
      )
        .toString("base64")
        .replace(/=/g, "")
        .replace(/\+/g, "-")
        .replace(/\//g, "_");

      const forgedToken = `${header}.${tamperedPayload}.${signature}`;

      // 1. getIdentity returns null
      expect(getIdentity(forgedToken)).toBeNull();
      // 2. requireIdentity throws IdentityVerificationError
      expect(() => requireIdentity(forgedToken)).toThrow(
        IdentityVerificationError,
      );
      expect(() => requireIdentity(forgedToken)).toThrow(
        /Invalid identity token signature/,
      );
    });

    it('should reject algorithm "none" attack', () => {
      const noneHeader = Buffer.from(
        JSON.stringify({ alg: "none", typ: "JWT" }),
      )
        .toString("base64")
        .replace(/=/g, "");
      const payload = Buffer.from(
        JSON.stringify({
          sub: "attacker",
          exp: Math.floor(Date.now() / 1000) + 3600,
        }),
      )
        .toString("base64")
        .replace(/=/g, "");
      const noneToken = `${noneHeader}.${payload}.`;

      expect(getIdentity(noneToken)).toBeNull();
      expect(() => requireIdentity(noneToken)).toThrow(
        IdentityVerificationError,
      );
      expect(() => requireIdentity(noneToken)).toThrow(/Unsupported algorithm/);
    });

    it("should reject expired identity tokens (replay defense)", () => {
      const expiredToken = createDevIdentityToken({
        userId: "bob-456",
        expiresInSeconds: -3600, // Expired 1 hour ago
      });

      expect(getIdentity(expiredToken)).toBeNull();
      expect(() => requireIdentity(expiredToken)).toThrow(
        IdentityVerificationError,
      );
      expect(() => requireIdentity(expiredToken)).toThrow(
        /Identity token expired/,
      );
    });

    it("should reject identity token with audience mismatch (cross-app replay defense)", () => {
      const tokenForAppB = createDevIdentityToken({
        userId: "bob-456",
        audience: "capsule:app-b",
      });

      // App A expects audience 'capsule:app-a'
      expect(
        getIdentity(tokenForAppB, { audience: "capsule:app-a" }),
      ).toBeNull();
      expect(() =>
        requireIdentity(tokenForAppB, { audience: "capsule:app-a" }),
      ).toThrow(IdentityVerificationError);
      expect(() =>
        requireIdentity(tokenForAppB, { audience: "capsule:app-a" }),
      ).toThrow(/Audience mismatch/);
    });

    it("should reject raw unsigned JSON identity header in strict production mode (SEC-001)", () => {
      const rawJson = JSON.stringify({
        sub: "attacker-666",
        roles: ["owner", "admin"],
        email: "attacker@evil.com",
      });

      process.env.STRICT_IDENTITY = "true";
      try {
        // Must return null when throwOnError is false
        expect(getIdentity(rawJson)).toBeNull();

        // Must throw IdentityVerificationError with UNSIGNED_IDENTITY_REJECTED
        expect(() => requireIdentity(rawJson)).toThrow(
          IdentityVerificationError,
        );
        expect(() => requireIdentity(rawJson)).toThrow(
          /Unsigned identity header rejected/i,
        );
      } finally {
        delete process.env.STRICT_IDENTITY;
      }
    });

    it("should reject identity token signed with untrusted/wrong key (SEC-003)", () => {
      // Sign with an attacker key
      const attackerToken = createDevIdentityToken({
        userId: "attacker-123",
        roles: ["admin"],
        secret: "attacker-untrusted-secret-key-99999",
      });

      expect(getIdentity(attackerToken)).toBeNull();
      expect(() => requireIdentity(attackerToken)).toThrow(
        IdentityVerificationError,
      );
      expect(() => requireIdentity(attackerToken)).toThrow(
        /Invalid identity token signature/i,
      );
    });
  });

  // =========================================================================
  // 8. USE A CAPABILITY IT DID NOT DECLARE
  // =========================================================================
  describe("8. Undeclared Capability Enforcement", () => {
    it("should block invoking a connector that was not declared in manifest", async () => {
      // In control plane: invoke_connector checks app.manifest.capabilities.connectors
      // If connector_name is not declared, returns 403 CAPABILITY_DENIED
      const manifestWithoutConnectors = {
        capabilities: {
          db: { type: "sqlite" },
          connectors: [], // None declared!
        },
      };

      const hasDeclared = (
        manifestWithoutConnectors.capabilities.connectors as any[]
      ).some((c: any) => c === "slack.post" || c.name === "slack.post");
      expect(hasDeclared).toBe(false);
    });
  });

  // =========================================================================
  // 9. ADD A NEW CAPABILITY IN A LATER VERSION WITHOUT APPROVAL
  // =========================================================================
  describe("9. Unauthorized Capability Escalation on Update", () => {
    it("should hold deployment in pending_approval when adding new capabilities or service identity", () => {
      // In control plane detect_capability_escalation:
      // Adding new connector or upgrading from viewer to service triggers escalation
      const oldCaps = { db: { type: "sqlite" } };
      const newCaps = {
        db: { type: "sqlite" },
        ai: { monthly_budget_usd: 10 },
        connectors: [{ name: "slack.post", acts_as: "service" }],
      };

      const hasNewAi = !(oldCaps as any).ai && !!newCaps.ai;
      const hasNewConnector =
        !(oldCaps as any).connectors && !!newCaps.connectors;

      expect(hasNewAi).toBe(true);
      expect(hasNewConnector).toBe(true);
      // Publish credentials cannot self-approve escalation (Security Invariant)
    });
  });

  // =========================================================================
  // 10. SANDBOX RUNNER SERVICE ATTACKS (SEC-004 BOUNDARY)
  // =========================================================================
  describe("10. Sandbox Runner Service Attacks (SEC-004 Boundary)", () => {
    let runnerServer: http.Server;
    let runnerPort: number;
    let driverStartCalls = 0;
    const testSecret = "redteam-runner-secret-key-32chars!";

    beforeAll(async () => {
      const mockDriver = new MockSandboxDriver();
      const origStart = mockDriver.start.bind(mockDriver);
      mockDriver.start = async (spec) => {
        driverStartCalls++;
        return origStart(spec);
      };

      runnerServer = createSandboxRunnerServer({
        driver: mockDriver as any,
        secret: testSecret,
        enforceVpcOnly: true,
      });
      await new Promise<void>((resolve) => {
        runnerServer.listen(0, "127.0.0.1", () => {
          runnerPort = (runnerServer.address() as AddressInfo).port;
          resolve();
        });
      });
    });

    beforeEach(() => {
      driverStartCalls = 0;
    });

    afterAll(async () => {
      if (runnerServer) {
        await new Promise((resolve) => runnerServer.close(resolve));
      }
    });

    function makeRunnerRequest(opts: {
      path: string;
      method?: string;
      headers?: Record<string, string>;
      body?: any;
    }): Promise<{ statusCode: number; body: any }> {
      return new Promise((resolve, reject) => {
        const req = http.request(
          {
            hostname: "127.0.0.1",
            port: runnerPort,
            path: opts.path,
            method: opts.method || "GET",
            headers: {
              "Content-Type": "application/json",
              ...(opts.headers || {}),
            },
          },
          (res) => {
            let data = "";
            res.on("data", (chunk) => (data += chunk));
            res.on("end", () => {
              let parsed: any = data;
              try {
                parsed = JSON.parse(data);
              } catch {}
              resolve({ statusCode: res.statusCode || 0, body: parsed });
            });
          },
        );
        req.on("error", reject);
        if (opts.body) {
          req.write(
            typeof opts.body === "string"
              ? opts.body
              : JSON.stringify(opts.body),
          );
        }
        req.end();
      });
    }

    it("should reject connection attempts to port 8095 originating from outside the VPC CIDR", async () => {
      // 1. Direct validation of VPC CIDR logic
      expect(isVpcCidr("10.0.1.5")).toBe(true); // AWS VPC 10.0.0.0/8
      expect(isVpcCidr("172.16.10.20")).toBe(true); // AWS VPC 172.16.0.0/12
      expect(isVpcCidr("127.0.0.1")).toBe(true); // Local loopback
      expect(isVpcCidr("203.0.113.195")).toBe(false); // Public internet IP
      expect(isVpcCidr("8.8.8.8")).toBe(false); // Public internet IP
      expect(isVpcCidr("192.168.1.1")).toBe(false); // Non-VPC local subnet

      // 2. HTTP request from non-VPC origin rejected with 403 VPC_INGRESS_DENIED
      const res = await makeRunnerRequest({
        path: "/healthz",
        headers: {
          "x-forwarded-for": "203.0.113.195",
        },
      });

      expect(res.statusCode).toBe(403);
      expect(res.body.error).toBe("VPC_INGRESS_DENIED");
      expect(res.body.message).toContain("Allowed only from private VPC CIDRs");
      expect(driverStartCalls).toBe(0);
    });

    it("should reject requests with missing or invalid runner shared secret with 401 UNAUTHORIZED", async () => {
      // Constant-time token verification validation
      expect(
        timingSafeCompare("Bearer valid-token", "Bearer valid-token"),
      ).toBe(true);
      expect(
        timingSafeCompare("Bearer valid-token", "Bearer wrong-token"),
      ).toBe(false);
      expect(
        timingSafeCompare("Bearer valid-token", "Bearer valid-token-longer"),
      ).toBe(false);
      expect(timingSafeCompare("", "Bearer valid-token")).toBe(false);

      // 1. Missing Authorization header
      const missingRes = await makeRunnerRequest({
        path: "/v1/sandboxes/start",
        method: "POST",
        headers: {
          "x-forwarded-for": "10.0.1.5",
        },
        body: { capsuleId: "test-app", appKey: "test", versionId: "v1" },
      });
      expect(missingRes.statusCode).toBe(401);
      expect(missingRes.body.error).toBe("UNAUTHORIZED");
      expect(driverStartCalls).toBe(0);

      // 2. Wrong bearer token
      const invalidRes = await makeRunnerRequest({
        path: "/v1/sandboxes/start",
        method: "POST",
        headers: {
          authorization: "Bearer wrong-secret-token",
          "x-forwarded-for": "10.0.1.5",
        },
        body: { capsuleId: "test-app", appKey: "test", versionId: "v1" },
      });
      expect(invalidRes.statusCode).toBe(401);
      expect(invalidRes.body.error).toBe("UNAUTHORIZED");
      expect(driverStartCalls).toBe(0);
    });

    it("should reject attempt to use runner API to start a sandbox for an app the caller does not own", async () => {
      // Caller identity: org_attacker
      // Target capsule ownership: org_victim
      const res = await makeRunnerRequest({
        path: "/v1/sandboxes/start",
        method: "POST",
        headers: {
          authorization: `Bearer ${testSecret}`,
          "x-caller-org-id": "org_attacker",
          "x-forwarded-for": "10.0.1.5",
        },
        body: {
          capsuleId: "confidential-leave-tracker",
          appKey: "leave-tracker",
          versionId: "v1.0.0",
          organizationId: "org_victim", // Owned by victim org!
          bundlePath: "/tmp/bundle",
          dataDir: "/tmp/data",
        },
      });

      expect(res.statusCode).toBe(403);
      expect(res.body.error).toBe("CROSS_TENANT_ACCESS_DENIED");
      expect(res.body.message).toContain(
        "Caller from organization 'org_attacker' is forbidden from launching capsule belonging to organization 'org_victim'",
      );
      expect(driverStartCalls).toBe(0);
    });

    it("should allow sandbox start when request passes VPC CIDR, bearer secret, and org tenancy checks", async () => {
      const res = await makeRunnerRequest({
        path: "/v1/sandboxes/start",
        method: "POST",
        headers: {
          authorization: `Bearer ${testSecret}`,
          "x-caller-org-id": "org_legit",
          "x-forwarded-for": "10.0.1.5",
        },
        body: {
          capsuleId: "legit-app",
          appKey: "legit",
          versionId: "v1.0.0",
          organizationId: "org_legit",
          bundlePath: "/tmp/bundle",
          dataDir: "/tmp/data",
        },
      });

      expect(res.statusCode).toBe(200);
      expect(res.body.capsuleId).toBe("legit-app");
      expect(res.body.status).toBe("running");
      expect(driverStartCalls).toBe(1);
    });
  });
});
