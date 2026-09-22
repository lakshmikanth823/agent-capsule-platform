import { describe, it, expect, beforeAll, afterAll, beforeEach } from "vitest";
import http from "node:http";
import {
  createEgressProxyServer,
  EgressPolicyManager,
  EgressLogger,
} from "../src/index.js";

describe("Egress Proxy Kill Switch & Quotas (Prompt 23)", () => {
  let proxyServer: http.Server;
  let targetHttpServer: http.Server;
  let policyManager: EgressPolicyManager;
  let logger: EgressLogger;

  const PROXY_PORT = 19180;
  const TARGET_PORT = 19181;

  beforeAll(async () => {
    policyManager = new EgressPolicyManager();
    logger = new EgressLogger();

    // Target server to simulate destination
    targetHttpServer = http.createServer((req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, host: req.headers.host }));
    });
    await new Promise((resolve) =>
      targetHttpServer.listen(TARGET_PORT, "127.0.0.1", () => resolve(true)),
    );

    proxyServer = createEgressProxyServer({
      policyManager,
      logger,
      dnsResolver: {
        lookup: async (hostname: string) => {
          return [{ address: "93.184.216.34", family: 4 }];
        },
      },
    });
    await new Promise((resolve) =>
      proxyServer.listen(PROXY_PORT, "127.0.0.1", () => resolve(true)),
    );
  });

  afterAll(async () => {
    await new Promise((resolve) => proxyServer.close(resolve));
    await new Promise((resolve) => targetHttpServer.close(resolve));
  });

  beforeEach(() => {
    logger.clear();
    policyManager.clear();
  });

  it("blocks egress when app is suspended via kill switch", async () => {
    const appKey = "test-suspended-app";
    policyManager.setPolicy(appKey, {
      appKey,
      appAllowlist: [{ host: "api.example.com", port: 80 }],
    });

    // 1. Suspend app
    policyManager.suspendApp(appKey);
    expect(policyManager.isAppSuspended(appKey)).toBe(true);

    // 2. Outbound request should be blocked
    const res = await fetch(`http://127.0.0.1:${PROXY_PORT}/test`, {
      headers: {
        "x-capsule-app-key": appKey,
        Host: "api.example.com",
      },
    });

    expect(res.status).toBe(403);
    const data = await res.json();
    expect(data.code).toBe("APP_SUSPENDED");

    // 3. Resume app
    policyManager.resumeApp(appKey);
    expect(policyManager.isAppSuspended(appKey)).toBe(false);
  });

  it("blocks egress when organization is frozen", async () => {
    const appKey = "test-org-app";
    const orgId = "org-breached";
    policyManager.setPolicy(appKey, {
      appKey,
      appAllowlist: [{ host: "api.example.com", port: 80 }],
    });

    // 1. Freeze organization
    policyManager.freezeOrg(orgId);
    expect(policyManager.isOrgFrozen(orgId)).toBe(true);

    // 2. Request from app with frozen org header
    const res = await fetch(`http://127.0.0.1:${PROXY_PORT}/test`, {
      headers: {
        "x-capsule-app-key": appKey,
        "x-capsule-org-id": orgId,
        Host: "api.example.com",
      },
    });

    expect(res.status).toBe(403);
    const data = await res.json();
    expect(data.code).toBe("ORGANIZATION_FROZEN");

    // 3. Resume organization
    policyManager.resumeOrg(orgId);
    expect(policyManager.isOrgFrozen(orgId)).toBe(false);
  });

  it("enforces daily egress byte quota (HTTP 403 QUOTA_EXCEEDED)", async () => {
    const appKey = "test-quota-app";
    policyManager.setPolicy(appKey, {
      appKey,
      appAllowlist: [{ host: "api.example.com", port: 80 }],
      dailyByteLimit: 1000, // 1000 bytes limit for test
    });

    // Send request with body under quota
    const smallPayload = "A".repeat(500);
    const check1 = policyManager.checkAndTrackEgress(
      appKey,
      smallPayload.length,
    );
    expect(check1.allowed).toBe(true);

    // Next request exceeds remaining 500 bytes
    const check2 = policyManager.checkAndTrackEgress(appKey, 600);
    expect(check2.allowed).toBe(false);

    // Send HTTP request to proxy that exceeds daily quota
    const res = await fetch(`http://127.0.0.1:${PROXY_PORT}/test`, {
      method: "POST",
      headers: {
        "x-capsule-app-key": appKey,
        Host: "api.example.com",
        "Content-Type": "text/plain",
      },
      body: "B".repeat(600),
    });

    expect(res.status).toBe(403);
    const data = await res.json();
    expect(data.code).toBe("QUOTA_EXCEEDED");
    expect(data.metric).toBe("egress_bytes_per_day");
  });
});
