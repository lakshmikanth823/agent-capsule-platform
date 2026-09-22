import { describe, it, expect, beforeAll, afterAll } from "vitest";
import http from "node:http";
import { AddressInfo } from "node:net";
import path from "node:path";
import fs from "node:fs";
import {
  createEdgeProxyServer,
  AccessManager,
  type AppMetadata,
} from "../../services/edge-proxy/src/index.js";
import {
  CapsuleLifecycleManager,
  DevMockSandboxDriver,
  type ForwardRequest,
  type ForwardResponse,
} from "@capsule/sandbox-driver";

describe("Staging E2E Test: Leave Tracker Sharing & Data Isolation", () => {
  let server: http.Server;
  let serverPort: number;
  let lifecycleManager: CapsuleLifecycleManager;
  let accessManager: AccessManager;

  const appDomain = "apps.localhost";
  const dashboardDomain = "platform.localhost";
  const testDbDir = path.resolve("data/test-e2e-leave-tracker");

  // In-memory capsule database simulating SQLite persistence
  const leaveStore = new Map<
    string,
    Array<{
      id: number;
      userId: string;
      reason: string;
      startDate: string;
      endDate: string;
    }>
  >();
  let nextLeaveId = 1;

  class LeaveTrackerE2EDriver extends DevMockSandboxDriver {
    async forwardRequest(
      instanceId: string,
      req: ForwardRequest,
    ): Promise<ForwardResponse> {
      const identityJwt = req.headers["x-capsule-identity"];
      let identity: any = null;
      if (identityJwt) {
        try {
          const parts = identityJwt.split(".");
          identity = JSON.parse(Buffer.from(parts[1], "base64url").toString());
        } catch {}
      }

      const url = new URL(req.path, "http://localhost");

      // 1. Health check
      if (url.pathname === "/health") {
        return {
          statusCode: 200,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status: "healthy",
            app: "leave-tracker",
            version: "1.0.0",
          }),
        };
      }

      // 2. Identity inspection
      if (url.pathname === "/api/identity") {
        return {
          statusCode: 200,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ authenticated: Boolean(identity), identity }),
        };
      }

      // 3. Leaves CRUD
      if (url.pathname === "/api/leaves") {
        const capsuleId = "app-leave-tracker-e2e";
        if (!leaveStore.has(capsuleId)) {
          leaveStore.set(capsuleId, []);
        }
        const appLeaves = leaveStore.get(capsuleId)!;

        if (req.method === "POST") {
          const body = req.body ? JSON.parse(req.body) : {};
          const leave = {
            id: nextLeaveId++,
            userId: identity?.sub || "anonymous",
            reason: body.reason || "Vacation",
            startDate: body.start_date || "2026-10-01",
            endDate: body.end_date || "2026-10-05",
          };
          appLeaves.push(leave);
          return {
            statusCode: 201,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(leave),
          };
        }

        if (req.method === "GET") {
          const isManager =
            identity?.roles?.includes("manager") ||
            identity?.roles?.includes("owner") ||
            identity?.roles?.includes("hr");
          const visible = isManager
            ? appLeaves
            : appLeaves.filter((l) => l.userId === identity?.sub);

          return {
            statusCode: 200,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ leaves: visible }),
          };
        }
      }

      return super.forwardRequest(instanceId, req);
    }
  }

  const sampleApp: AppMetadata = {
    id: "app-leave-tracker-e2e",
    appKey: "leave-tracker",
    name: "Leave Tracker",
    organizationId: "org_acme",
    ownerUserId: "usr_alice_123",
    status: "active",
    manifest: {
      id: "leave-tracker",
      roles: ["employee", "manager", "hr"],
      capabilities: { db: { type: "sqlite" }, identity: true },
    },
    bundlePath: path.resolve("examples/leave-tracker"),
    dataDir: testDbDir,
    defaultScope: "restricted",
  };

  beforeAll(async () => {
    fs.mkdirSync(testDbDir, { recursive: true });

    const driver = new LeaveTrackerE2EDriver();
    lifecycleManager = new CapsuleLifecycleManager({ driver });
    accessManager = new AccessManager();
    accessManager.registerApp(sampleApp);

    server = createEdgeProxyServer({
      config: { appDomain, dashboardDomain },
      lifecycleManager,
      accessManager,
    });

    await new Promise<void>((resolve) => {
      server.listen(0, "127.0.0.1", () => {
        serverPort = (server.address() as AddressInfo).port;
        resolve();
      });
    });
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    fs.rmSync(testDbDir, { recursive: true, force: true });
  });

  function makeRequest(options: {
    host: string;
    path: string;
    method?: string;
    headers?: Record<string, string>;
    body?: string;
  }): Promise<{
    statusCode: number;
    headers: http.IncomingHttpHeaders;
    body: string;
  }> {
    return new Promise((resolve, reject) => {
      const req = http.request(
        {
          hostname: "127.0.0.1",
          port: serverPort,
          path: options.path,
          method: options.method || "GET",
          headers: {
            host: options.host,
            ...(options.headers || {}),
          },
        },
        (res) => {
          let body = "";
          res.on("data", (chunk) => (body += chunk));
          res.on("end", () =>
            resolve({
              statusCode: res.statusCode || 0,
              headers: res.headers,
              body,
            }),
          );
        },
      );
      req.on("error", reject);
      if (options.body) req.write(options.body);
      req.end();
    });
  }

  it("Step 1: Unauthenticated colleague visiting capsule subdomain is redirected to Platform SSO login", async () => {
    const res = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: "/",
    });
    expect(res.statusCode).toBe(302);
    expect(res.headers.location).toContain(
      "/auth/login?target_app=leave-tracker",
    );
  });

  it("Step 2: Owner (Alice) logs in, accesses capsule, and verifies identity and roles", async () => {
    // 1. Get auth ticket from platform IdP
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=alice&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    expect(ticketRes.statusCode).toBe(302);
    const ticket = new URL(ticketRes.headers.location || "").searchParams.get(
      "ticket",
    );
    expect(ticket).toBeDefined();

    // 2. Complete callback handshake on app origin
    const callbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });
    expect(callbackRes.statusCode).toBe(302);
    const cookie = callbackRes.headers["set-cookie"]?.[0]?.split(";")[0] || "";
    expect(cookie).toContain("capsule_session=");

    // 3. Access /api/identity
    const identityRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: "/api/identity",
      headers: { cookie },
    });
    expect(identityRes.statusCode).toBe(200);
    const data = JSON.parse(identityRes.body);
    expect(data.authenticated).toBe(true);
    expect(data.identity.sub).toBe("usr_alice_123");
    expect(data.identity.roles).toContain("employee");
  });

  it("Step 3: Unshared colleague (Bob) is denied access", async () => {
    // Bob attempts to complete login ticket without a share
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=bob&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const ticket = new URL(ticketRes.headers.location || "").searchParams.get(
      "ticket",
    );

    const callbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });
    expect(callbackRes.statusCode).toBe(403);
    expect(callbackRes.body).toContain("Access Denied");
  });

  it("Step 4: Owner shares capsule with colleague (Bob as employee); Bob logs in and creates data", async () => {
    // Owner shares app with Bob (bob@example.com)
    accessManager.addShare({
      appKey: "leave-tracker",
      userEmail: "bob@example.com",
      appRole: "employee",
    });

    // Bob completes handshake
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=bob&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const ticket = new URL(ticketRes.headers.location || "").searchParams.get(
      "ticket",
    );

    const callbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });
    expect(callbackRes.statusCode).toBe(302);
    const bobCookie =
      callbackRes.headers["set-cookie"]?.[0]?.split(";")[0] || "";

    // Bob creates a leave request in his shared app
    const createRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: "/api/leaves",
      method: "POST",
      headers: {
        cookie: bobCookie,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        reason: "Family vacation",
        start_date: "2026-12-01",
        end_date: "2026-12-07",
      }),
    });
    expect(createRes.statusCode).toBe(201);
    const created = JSON.parse(createRes.body);
    expect(created.id).toBeDefined();
    expect(created.userId).toBe("usr_bob_456");
    expect(created.reason).toBe("Family vacation");

    // Bob fetches leaves — verifies his leave appears
    const getRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: "/api/leaves",
      headers: { cookie: bobCookie },
    });
    expect(getRes.statusCode).toBe(200);
    const list = JSON.parse(getRes.body);
    expect(list.leaves.some((l: any) => l.reason === "Family vacation")).toBe(
      true,
    );
  });

  it("Step 5: Proves data isolation between colleagues", async () => {
    // Alice also logs in and creates her own leave request
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=alice&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const ticket = new URL(ticketRes.headers.location || "").searchParams.get(
      "ticket",
    );
    const callbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });
    const aliceCookie =
      callbackRes.headers["set-cookie"]?.[0]?.split(";")[0] || "";

    await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: "/api/leaves",
      method: "POST",
      headers: {
        cookie: aliceCookie,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        reason: "Alice Executive Retreat",
        start_date: "2026-12-10",
        end_date: "2026-12-12",
      }),
    });

    // Bob logs in again as employee and queries leaves
    const bobTicketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=bob&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const bobTicket = new URL(
      bobTicketRes.headers.location || "",
    ).searchParams.get("ticket");
    const bobCallbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${bobTicket}&return_to=/`,
    });
    const bobCookie =
      bobCallbackRes.headers["set-cookie"]?.[0]?.split(";")[0] || "";

    const bobGetRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: "/api/leaves",
      headers: { cookie: bobCookie },
    });
    const bobList = JSON.parse(bobGetRes.body);

    // Data Isolation: Bob (employee) CANNOT see Alice's leave request
    expect(
      bobList.leaves.some((l: any) => l.reason === "Alice Executive Retreat"),
    ).toBe(false);
    // Bob CAN see his own leave request
    expect(
      bobList.leaves.some((l: any) => l.reason === "Family vacation"),
    ).toBe(true);

    // Alice (owner/manager) CAN see both
    const aliceGetRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: "/api/leaves",
      headers: { cookie: aliceCookie },
    });
    const aliceList = JSON.parse(aliceGetRes.body);
    expect(
      aliceList.leaves.some((l: any) => l.reason === "Alice Executive Retreat"),
    ).toBe(true);
    expect(
      aliceList.leaves.some((l: any) => l.reason === "Family vacation"),
    ).toBe(true);
  });
});
