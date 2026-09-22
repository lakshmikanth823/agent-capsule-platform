import { describe, it, expect, beforeAll, afterAll } from "vitest";
import http from "node:http";
import { AddressInfo } from "node:net";
import {
  createEdgeProxyServer,
  createSessionToken,
  createHostOnlyCookie,
  AccessManager,
} from "../src/index.js";
import {
  DevMockSandboxDriver,
  CapsuleLifecycleManager,
} from "@capsule/sandbox-driver";

describe("Edge Proxy Google Sheets Consent Suite (Prompt 25)", () => {
  let server: http.Server;
  let serverPort: number;
  let mockDriver: DevMockSandboxDriver;
  let lifecycleManager: CapsuleLifecycleManager;
  let accessManager: AccessManager;

  const appDomain = "apps.localhost";
  const dashboardDomain = "platform.localhost";
  const sessionSecret = "test-session-secret-key-32-bytes-long!";

  let aliceCookie: string;

  beforeAll(async () => {
    mockDriver = new DevMockSandboxDriver();
    lifecycleManager = new CapsuleLifecycleManager({ driver: mockDriver });
    accessManager = new AccessManager();

    // Register test app declaring sheets.read with acts_as: viewer and spreadsheet_ids
    accessManager.registerApp({
      id: "app-sheets-viewer",
      appKey: "sheets-viewer",
      name: "Sheets Viewer Capsule",
      organizationId: "org_acme",
      status: "active",
      manifest: {
        id: "sheets-viewer",
        capabilities: {
          identity: true,
          connectors: [
            {
              name: "sheets.read",
              acts_as: "viewer",
              spreadsheet_ids: ["sheet-finance-2026", "sheet-hr-roster"],
            },
          ],
        },
      },
    });

    server = createEdgeProxyServer({
      config: {
        appDomain,
        dashboardDomain,
        sessionSecret,
      },
      lifecycleManager,
      accessManager,
    });

    await new Promise<void>((resolve) => {
      server.listen(0, "127.0.0.1", () => {
        serverPort = (server.address() as AddressInfo).port;
        resolve();
      });
    });

    // Create session cookie for Alice
    const token = createSessionToken(
      {
        sub: "usr_alice_123",
        email: "alice@example.com",
        org_id: "org_acme",
        app_key: "sheets-viewer",
        platform_role: "owner",
        app_roles: ["employee"],
      },
      sessionSecret,
    );
    aliceCookie = `capsule_session=${token}`;
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  function makeRequest(options: {
    host: string;
    path: string;
    method?: string;
    headers?: Record<string, string>;
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
      req.end();
    });
  }

  it("1. should intercept first-time user and show consent screen with requested scopes and spreadsheets", async () => {
    const res = await makeRequest({
      host: `sheets-viewer.${appDomain}`,
      path: "/",
      headers: {
        cookie: aliceCookie,
      },
    });

    expect(res.statusCode).toBe(200);
    expect(res.headers["content-type"]).toContain("text/html");
    expect(res.body).toContain("Connect Google Sheets");
    expect(res.body).toContain(
      "https://www.googleapis.com/auth/spreadsheets.readonly",
    );
    expect(res.body).toContain("sheet-finance-2026");
    expect(res.body).toContain("sheet-hr-roster");
    expect(res.body).toContain("Allow Access");
    expect(res.body).toContain("Cancel");
  });

  it("2. should render consent screen on direct /auth/connectors/consent route", async () => {
    const res = await makeRequest({
      host: `sheets-viewer.${appDomain}`,
      path: "/auth/connectors/consent?return_to=%2Fdashboard",
      headers: {
        cookie: aliceCookie,
      },
    });

    expect(res.statusCode).toBe(200);
    expect(res.body).toContain("Connect Google Sheets");
    expect(res.body).toContain("return_to=%2Fdashboard");
  });

  it("3. should set consent cookie and redirect on /auth/connectors/google/authorize", async () => {
    const res = await makeRequest({
      host: `sheets-viewer.${appDomain}`,
      path: "/auth/connectors/google/authorize?app=sheets-viewer&return_to=%2Foverview",
      headers: {
        cookie: aliceCookie,
      },
    });

    expect(res.statusCode).toBe(302);
    expect(res.headers.location).toBe("/overview");
    const setCookie = res.headers["set-cookie"]?.join(";") || "";
    expect(setCookie).toContain("capsule_consent_sheets-viewer_sheets=1");
  });

  it("4. should render cancellation page on /auth/cancel", async () => {
    const res = await makeRequest({
      host: `sheets-viewer.${appDomain}`,
      path: "/auth/cancel?return_to=%2F",
      headers: {
        cookie: aliceCookie,
      },
    });

    expect(res.statusCode).toBe(200);
    expect(res.body).toContain("Authorization Cancelled");
  });

  it("5. should proceed and forward request to sandbox when consent cookie is present", async () => {
    const consentedCookie = `${aliceCookie}; capsule_consent_sheets-viewer_sheets=1`;

    const res = await makeRequest({
      host: `sheets-viewer.${appDomain}`,
      path: "/api/data",
      headers: {
        cookie: consentedCookie,
      },
    });

    // Mock driver forwards and responds with 200 JSON
    expect(res.statusCode).toBe(200);
    expect(res.body).not.toContain("Connect Google Sheets");
  });
});
