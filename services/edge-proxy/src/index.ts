/**
 * @capsule/edge-proxy
 *
 * Edge reverse proxy providing per-Capsule origin isolation,
 * hostname-based routing, per-app host-only authentication handshake,
 * access control, role mapping, wake-on-request container management,
 * signed identity injection with key rotation, and security headers.
 */
import http from "node:http";
import path from "node:path";
import fs from "node:fs";
import { loadConfig, type ProxyConfig } from "./config.js";
import { signJwt, verifyJwt } from "./crypto.js";
import {
  createHostOnlyCookie,
  getSessionFromRequest,
  createSessionToken,
  createClearCookie,
  type AppSession,
} from "./session.js";
import {
  renderAppNotFoundPage,
  renderNotAuthorizedPage,
  renderPlatformLoginPage,
  renderAppSuspendedPage,
  renderOrgSuspendedPage,
  renderConsentScreen,
} from "./pages.js";
import { AccessManager, type UserContext } from "./access.js";
import {
  CapsuleLifecycleManager,
  DevMockSandboxDriver,
  type ForwardRequest,
} from "@capsule/sandbox-driver";

export * from "./config.js";
export * from "./crypto.js";
export * from "./session.js";
export * from "./access.js";
export * from "./pages.js";

export function extractSubdomainCapsuleId(
  hostname: string,
  appDomain = "apps.localhost",
): string | null {
  const hostWithoutPort = hostname.split(":")[0].toLowerCase();
  const normalizedAppDomain = appDomain.toLowerCase();

  if (hostWithoutPort.endsWith(`.${normalizedAppDomain}`)) {
    const subdomain = hostWithoutPort.slice(
      0,
      -(normalizedAppDomain.length + 1),
    );
    return subdomain || null;
  }
  return null;
}

export function applySecurityHeaders(
  res: http.ServerResponse,
  isProduction = false,
): void {
  res.setHeader(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
  );
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");

  if (isProduction) {
    res.setHeader(
      "Strict-Transport-Security",
      "max-age=31536000; includeSubDomains",
    );
  }
}

export class PayloadTooLargeError extends Error {
  constructor(
    message: string,
    public readonly maxBytes: number,
  ) {
    super(message);
    this.name = "PayloadTooLargeError";
  }
}

function readRequestBody(
  req: http.IncomingMessage,
  maxBytes: number = 10 * 1024 * 1024,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const contentLength = req.headers["content-length"];
    if (contentLength && parseInt(contentLength, 10) > maxBytes) {
      return reject(
        new PayloadTooLargeError(
          `Request body size exceeds maximum limit of ${Math.round(maxBytes / (1024 * 1024))}MB.`,
          maxBytes,
        ),
      );
    }
    let body = "";
    let bytesReceived = 0;
    req.on("data", (chunk) => {
      bytesReceived += chunk.length;
      if (bytesReceived > maxBytes) {
        req.removeAllListeners("data");
        req.resume();
        return reject(
          new PayloadTooLargeError(
            `Request body size exceeds maximum limit of ${Math.round(maxBytes / (1024 * 1024))}MB.`,
            maxBytes,
          ),
        );
      }
      body += chunk;
    });

    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}

export function createEdgeProxyServer(options?: {
  config?: Partial<ProxyConfig>;
  lifecycleManager?: CapsuleLifecycleManager;
  accessManager?: AccessManager;
}): http.Server {
  const baseConfig = loadConfig();
  const config: ProxyConfig = { ...baseConfig, ...(options?.config || {}) };

  const accessManager = options?.accessManager || new AccessManager();
  const lifecycleManager =
    options?.lifecycleManager ||
    new CapsuleLifecycleManager({
      driver: new DevMockSandboxDriver(),
    });

  const inFlightRequests = new Map<string, Set<() => void>>();

  // Seed default sample app into access manager if empty
  if (!accessManager.getApp("leave-tracker")) {
    accessManager.registerApp({
      id: "app-leave-tracker",
      appKey: "leave-tracker",
      name: "Leave Tracker",
      organizationId: "org_acme",
      status: "active",
      manifest: {
        id: "leave-tracker",
        roles: ["employee", "manager", "hr"],
        capabilities: { db: { type: "sqlite" }, identity: true },
      },
      bundlePath: path.resolve("examples/leave-tracker"),
      dataDir: path.resolve("data/capsules/leave-tracker/data"),
    });
  }

  // Helper to dynamically resolve apps and shares from control plane
  async function resolveApp(appKey: string): Promise<any> {
    let app = accessManager.getApp(appKey);

    // Try fetching from control plane if not registered or to refresh shares
    try {
      const controlPlaneUrl =
        process.env.CONTROL_PLANE_URL || "http://127.0.0.1:8000";
      const serviceToken =
        process.env.CONTROL_PLANE_SERVICE_TOKEN || "Bearer mock-alice-token";
      const res = await fetch(`${controlPlaneUrl}/v1/apps/${appKey}`, {
        headers: { Authorization: serviceToken },
      });
      if (res.ok) {
        const data = (await res.json()) as any;
        const sharesRes = await fetch(
          `${controlPlaneUrl}/v1/apps/${appKey}/shares`,
          {
            headers: { Authorization: serviceToken },
          },
        );
        const sharesData = (
          sharesRes.ok ? await sharesRes.json() : { shares: [] }
        ) as any;

        if (!app) {
          app = {
            id: data.id,
            appKey: data.app_key,
            name: data.name,
            organizationId: data.organization_id,
            status: data.status,
            currentVersionId: data.current_version_id,
            manifest: data.manifest || {
              id: appKey,
              roles: ["employee", "manager"],
            },
            bundlePath: path.resolve(`examples/${appKey}`),
            dataDir: path.resolve(`data/capsules/${appKey}/data`),
          };
          accessManager.registerApp(app);
        }

        // Synchronize active and revoked shares (SEC-007 fix)
        for (const s of sharesData.shares || []) {
          if (s.status === "active") {
            const existing = accessManager.listShares(appKey);
            const alreadyPresent = existing.some(
              (ex) =>
                (ex.userEmail === s.user_email || ex.userId === s.user_id) &&
                ex.status === "active",
            );
            if (!alreadyPresent) {
              accessManager.addShare({
                appKey,
                userId: s.user_id,
                userEmail: s.user_email,
                groupName: s.group_name,
                appRole: s.app_role,
              });
            }
          } else {
            // Evict revoked or expired share from local cache
            if (s.user_id) accessManager.revokeUserShares(appKey, s.user_id);
            if (s.user_email)
              accessManager.revokeUserShares(appKey, s.user_email);
          }
        }
      }
    } catch {
      // ignore
    }
    return app || accessManager.getApp(appKey);
  }

  const server = http.createServer(async (req, res) => {
    applySecurityHeaders(res, config.isProduction);

    const hostHeader = req.headers.host || "localhost";
    const hostWithoutPort = hostHeader.split(":")[0].toLowerCase();
    const url = new URL(req.url || "/", `http://${hostHeader}`);
    const pathname = url.pathname;

    // 1. Route: Dashboard / Platform Domain
    if (hostWithoutPort === config.dashboardDomain.toLowerCase()) {
      // Platform Login Page
      if (pathname === "/auth/login") {
        const targetApp = url.searchParams.get("target_app") || "leave-tracker";
        const returnTo =
          url.searchParams.get("return_to") ||
          `http://${targetApp}.${config.appDomain}:${config.port}/auth/callback`;
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(renderPlatformLoginPage(targetApp, returnTo));
        return;
      }

      // Platform Auth Ticket Issue (Mock IdP / SSO Handshake)
      if (pathname === "/auth/ticket") {
        const userChoice = url.searchParams.get("user") || "alice";
        const targetApp = url.searchParams.get("target_app") || "leave-tracker";
        const returnTo =
          url.searchParams.get("return_to") ||
          `http://${targetApp}.${config.appDomain}:${config.port}/auth/callback`;

        // Predefined mock users matching Prompt 05 & 06
        const mockUsers: Record<string, UserContext> = {
          alice: {
            id: "usr_alice_123",
            email: "alice@example.com",
            orgId: "org_acme",
            platformRole: "owner",
            groups: ["engineering"],
          },
          bob: {
            id: "usr_bob_456",
            email: "bob@example.com",
            orgId: "org_acme",
            platformRole: "user",
            groups: ["finance"],
          },
          charlie: {
            id: "usr_charlie_789",
            email: "charlie@other.com",
            orgId: "org_other",
            platformRole: "user",
            groups: ["sales"],
          },
        };

        const user = { ...(mockUsers[userChoice] || mockUsers.alice) };

        // If SSO is strictly enforced, block local mock ticket issuance
        if (process.env.ENFORCE_SSO === "true") {
          res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
          res.end(
            "Single Sign-On is enforced for your organization. Please sign in using corporate SSO.",
          );
          return;
        }

        // In dev mock IdP, align orgId with targetApp organization if available (unless external user Charlie)
        if (userChoice !== "charlie" && targetApp) {
          const targetAppMeta = await resolveApp(targetApp);
          if (targetAppMeta && targetAppMeta.organizationId) {
            user.orgId = targetAppMeta.organizationId;
          }
        }

        // Generate short-lived (60s) single-use handshake ticket
        const ticketPayload = {
          sub: user.id,
          email: user.email,
          org_id: user.orgId,
          platform_role: user.platformRole,
          groups: user.groups,
          target_app: targetApp,
          exp: Math.floor(Date.now() / 1000) + 60,
        };
        const ticket = signJwt(ticketPayload, config.sessionSecret);

        // Redirect back to app origin's /auth/callback
        const redirectUrl = new URL(returnTo);
        redirectUrl.searchParams.set("ticket", ticket);
        redirectUrl.searchParams.set("return_to", "/");

        res.writeHead(302, { Location: redirectUrl.toString() });
        res.end();
        return;
      }

      // Proxy /v1/* API calls to control plane
      if (pathname.startsWith("/v1")) {
        const controlPlaneUrl =
          process.env.CONTROL_PLANE_URL || "http://127.0.0.1:8000";
        const targetUrl = new URL(`${pathname}${url.search}`, controlPlaneUrl);
        const proxyReq = http.request(
          targetUrl,
          {
            method: req.method,
            headers: {
              ...req.headers,
              host: targetUrl.host,
            },
          },
          (proxyRes) => {
            res.writeHead(proxyRes.statusCode || 200, proxyRes.headers);
            proxyRes.pipe(res);
          },
        );
        proxyReq.on("error", (err) => {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(
            JSON.stringify({
              error: "Control plane unavailable",
              details: err.message,
            }),
          );
        });
        req.pipe(proxyReq);
        return;
      }

      // Serve Dashboard SPA Static Files
      const distDir = path.resolve("apps/dashboard/dist");
      const relativePath =
        pathname === "/" ? "index.html" : pathname.replace(/^\//, "");
      const filePath = path.join(distDir, relativePath);

      if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
        const ext = path.extname(filePath).toLowerCase();
        const mimeTypes: Record<string, string> = {
          ".html": "text/html; charset=utf-8",
          ".js": "application/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8",
          ".json": "application/json",
          ".png": "image/png",
          ".jpg": "image/jpeg",
          ".svg": "image/svg+xml",
          ".ico": "image/x-icon",
          ".woff2": "font/woff2",
        };
        const contentType = mimeTypes[ext] || "application/octet-stream";
        res.writeHead(200, { "Content-Type": contentType });
        fs.createReadStream(filePath).pipe(res);
        return;
      }

      // Fallback to index.html for SPA client-side routing
      const indexHtmlPath = path.join(distDir, "index.html");
      if (fs.existsSync(indexHtmlPath)) {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        fs.createReadStream(indexHtmlPath).pipe(res);
        return;
      }

      // Platform Root Fallback
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          platform: "Software Capsule Platform",
          domain: config.dashboardDomain,
        }),
      );
      return;
    }

    // 2. Route: App Subdomain (<app>.<APP_DOMAIN>)
    const appKey = extractSubdomainCapsuleId(hostHeader, config.appDomain);
    if (!appKey) {
      // Hostname does not match an app subdomain or platform domain
      res.writeHead(404, { "Content-Type": "text/html; charset=utf-8" });
      res.end(renderAppNotFoundPage("Unknown", hostHeader));
      return;
    }

    // A. App Auth Callback (Token Exchange Handshake)
    if (pathname === "/auth/callback") {
      const ticket = url.searchParams.get("ticket");
      const returnTo = url.searchParams.get("return_to") || "/";

      if (!ticket) {
        res.writeHead(400, { "Content-Type": "text/plain" });
        res.end("Missing ticket in callback.");
        return;
      }

      const verified = verifyJwt<any>(ticket, {
        default: config.sessionSecret,
      });
      if (!verified || verified.payload.target_app !== appKey) {
        res.writeHead(401, { "Content-Type": "text/plain" });
        res.end("Invalid, expired, or mismatched ticket.");
        return;
      }

      const ticketUser: UserContext = {
        id: verified.payload.sub,
        email: verified.payload.email,
        orgId: verified.payload.org_id,
        platformRole: verified.payload.platform_role,
        groups: verified.payload.groups,
      };

      // Check app existence and access
      const app = await resolveApp(appKey);
      if (!app) {
        res.writeHead(404, { "Content-Type": "text/html; charset=utf-8" });
        res.end(renderAppNotFoundPage(appKey, hostHeader));
        return;
      }

      const access = accessManager.evaluateAccess(ticketUser, app);
      if (!access.allowed) {
        res.writeHead(403, { "Content-Type": "text/html; charset=utf-8" });
        res.end(
          renderNotAuthorizedPage(
            appKey,
            ticketUser.email,
            ticketUser.orgId,
            access.reason,
          ),
        );
        return;
      }

      // Issue host-only cookie for this specific app origin
      const sessionData: Omit<AppSession, "iat" | "exp"> = {
        sub: ticketUser.id,
        email: ticketUser.email,
        org_id: ticketUser.orgId,
        app_key: appKey,
        platform_role: access.platformRole || "user",
        app_roles: access.appRoles || ["employee"],
        groups: ticketUser.groups,
      };

      const sessionToken = createSessionToken(
        sessionData,
        config.sessionSecret,
      );
      const hostOnlyCookie = createHostOnlyCookie(
        sessionToken,
        config.isProduction,
      );

      res.writeHead(302, {
        "Set-Cookie": hostOnlyCookie,
        Location: returnTo,
      });
      res.end();
      return;
    }

    // B. Check Session for App Request
    const session = getSessionFromRequest(
      req.headers.cookie,
      appKey,
      config.sessionSecret,
    );
    if (!session) {
      // Unauthenticated: Redirect to Platform Login Handshake
      const returnUrl = `http://${appKey}.${config.appDomain}:${config.port}/auth/callback`;
      const loginUrl = `http://${config.dashboardDomain}:${config.port}/auth/login?target_app=${appKey}&return_to=${encodeURIComponent(returnUrl)}`;
      res.writeHead(302, { Location: loginUrl });
      res.end();
      return;
    }

    // C. Check App Existence and Authorization
    const app = await resolveApp(appKey);
    if (!app) {
      res.writeHead(404, { "Content-Type": "text/html; charset=utf-8" });
      res.end(renderAppNotFoundPage(appKey, hostHeader));
      return;
    }

    const currentUser: UserContext = {
      id: session.sub,
      email: session.email,
      orgId: session.org_id,
      platformRole: session.platform_role,
      groups: session.groups,
    };

    const access = accessManager.evaluateAccess(currentUser, app);
    if (!access.allowed) {
      if (access.reason?.includes("Organization is suspended")) {
        res.writeHead(503, {
          "Content-Type": "text/html; charset=utf-8",
          "Set-Cookie": createClearCookie(config.isProduction),
        });
        res.end(renderOrgSuspendedPage(currentUser.orgId, access.reason));
        return;
      }
      if (access.reason?.includes("is suspended")) {
        res.writeHead(503, {
          "Content-Type": "text/html; charset=utf-8",
          "Set-Cookie": createClearCookie(config.isProduction),
        });
        res.end(renderAppSuspendedPage(appKey, access.reason));
        return;
      }
      res.writeHead(403, {
        "Content-Type": "text/html; charset=utf-8",
        "Set-Cookie": createClearCookie(config.isProduction),
      });
      res.end(
        renderNotAuthorizedPage(
          appKey,
          currentUser.email,
          currentUser.orgId,
          access.reason,
        ),
      );
      return;
    }

    // Check if app declares sheets.read or viewer connector
    const declaredConnectors = app.manifest?.capabilities?.connectors || [];
    let sheetsDecl: any = null;
    if (Array.isArray(declaredConnectors)) {
      for (const c of declaredConnectors) {
        if (
          typeof c === "string" &&
          (c === "sheets.read" || c === "google_sheets.read")
        ) {
          sheetsDecl = { name: c, acts_as: "viewer" };
          break;
        } else if (
          typeof c === "object" &&
          (c.name === "sheets.read" || c.name === "google_sheets.read")
        ) {
          sheetsDecl = c;
          break;
        }
      }
    } else if (typeof declaredConnectors === "object") {
      sheetsDecl =
        declaredConnectors["sheets.read"] ||
        declaredConnectors["google_sheets.read"];
    }

    // Consent Flow Routes for App Origin
    if (pathname === "/auth/connectors/consent") {
      const returnTo = url.searchParams.get("return_to") || "/";
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(
        renderConsentScreen({
          appKey,
          userEmail: currentUser.email,
          connectorName: sheetsDecl?.name || "sheets.read",
          scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
          spreadsheetIds: sheetsDecl?.spreadsheet_ids,
          returnTo,
        }),
      );
      return;
    }

    if (pathname === "/auth/connectors/google/authorize") {
      const returnTo = url.searchParams.get("return_to") || "/";
      const consentCookie = `capsule_consent_${appKey}_sheets=1; Path=/; HttpOnly; SameSite=Lax`;

      const controlPlaneUrl =
        process.env.CONTROL_PLANE_URL || "http://127.0.0.1:8000";
      try {
        await fetch(`${controlPlaneUrl}/v1/connectors/sheets.read/consent`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            access_token: `mock-google-token-${currentUser.id}`,
            refresh_token: `mock-google-refresh-${currentUser.id}`,
            expires_in: 3600,
            scope: "https://www.googleapis.com/auth/spreadsheets.readonly",
            user_id: currentUser.id,
            organization_id: currentUser.orgId,
          }),
        }).catch(() => {});
      } catch {}

      res.writeHead(302, {
        "Set-Cookie": consentCookie,
        Location: returnTo,
      });
      res.end();
      return;
    }

    if (pathname === "/auth/cancel") {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(
        `<!DOCTYPE html><html><body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; text-align: center; padding: 50px;">
          <h2>Authorization Cancelled</h2>
          <p>You cancelled authorization for Google Sheets. You can return to <a href="/">the application</a>.</p>
        </body></html>`,
      );
      return;
    }

    // Intercept first-time user opening an app requiring sheets.read without consent
    if (sheetsDecl && !pathname.startsWith("/auth")) {
      const cookieHeader = req.headers.cookie || "";
      const hasConsented = cookieHeader.includes(
        `capsule_consent_${appKey}_sheets=1`,
      );
      if (!hasConsented) {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(
          renderConsentScreen({
            appKey,
            userEmail: currentUser.email,
            connectorName: sheetsDecl.name || "sheets.read",
            scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
            spreadsheetIds: sheetsDecl.spreadsheet_ids,
            returnTo: pathname + (url.search || ""),
          }),
        );
        return;
      }
    }

    // D. Wake Capsule & Forward Request with Signed Identity Header
    let abortFn: (() => void) | null = null;
    let timer: NodeJS.Timeout | null = null;
    let isAborted = false;
    try {
      // 1. Quota Check: Request Body Size Limit
      const bodyLimitMb = app.manifest?.limits?.request_body_max_mb || 10;
      const rawBody = await readRequestBody(req, bodyLimitMb * 1024 * 1024);

      const forwardHeaders: Record<string, string> = {};
      for (const [k, v] of Object.entries(req.headers)) {
        if (v && typeof v === "string") forwardHeaders[k] = v;
      }

      // Capability enforcement: only inject identity context if declared in manifest
      if (app.manifest?.capabilities?.identity === true) {
        // Sign identity token using active key with key rotation support (kid)
        const now = Math.floor(Date.now() / 1000);
        const identityPayload = {
          iss: "platform",
          aud: `capsule:${app.id}`,
          sub: session.sub,
          email: session.email,
          org_id: session.org_id,
          groups: session.groups || [],
          roles: access.appRoles || session.app_roles || [],
          iat: now,
          exp: now + 300, // 5 minutes validity
        };

        const activeSecret =
          config.signingKeys[config.activeKeyId] ||
          Object.values(config.signingKeys)[0];
        const signedIdentityToken = signJwt(
          identityPayload,
          activeSecret,
          config.activeKeyId,
        );

        // Inject signed identity context
        forwardHeaders["x-capsule-identity"] = signedIdentityToken;
      }

      const forwardReq: ForwardRequest = {
        method: req.method || "GET",
        path: pathname + (url.search || ""),
        headers: forwardHeaders,
        body: rawBody,
      };

      // Prepare sandbox spec
      const spec = await lifecycleManager.prepareCapsule({
        capsuleId: app.id,
        versionId: app.currentVersionId || "v1",
        appKey: app.appKey,
        bundlePath: app.bundlePath || path.resolve(`examples/${app.appKey}`),
        customDataDir: app.dataDir,
        manifest: app.manifest,
      });

      // Track in-flight request for emergency abort
      isAborted = false;
      abortFn = () => {
        isAborted = true;
        if (timer) clearTimeout(timer);
        try {
          if (!res.headersSent) {
            res.writeHead(503, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                error: "APP_SUSPENDED",
                message: "Application has been suspended.",
              }),
            );
          }
        } catch {}
      };
      if (!inFlightRequests.has(appKey)) {
        inFlightRequests.set(appKey, new Set());
      }
      inFlightRequests.get(appKey)!.add(abortFn);

      // 2. Quota Check: Request Timeout Limit
      const timeoutSeconds = app.manifest?.limits?.request_timeout_s || 30;
      const timeoutPromise = new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          const timeoutErr = new Error(
            `Request execution time limit exceeded (${timeoutSeconds}s).`,
          );
          (timeoutErr as any).code = "TIMEOUT";
          reject(timeoutErr);
        }, timeoutSeconds * 1000);
      });

      // Wake-on-Request and forward with timeout
      const forwardRes = await Promise.race([
        lifecycleManager.handleRequest(spec, forwardReq),
        timeoutPromise,
      ]);

      if (timer) clearTimeout(timer);
      if (abortFn && inFlightRequests.has(appKey)) {
        inFlightRequests.get(appKey)!.delete(abortFn);
      }

      if (isAborted) return;

      // Return capsule response to client
      for (const [hk, hv] of Object.entries(forwardRes.headers)) {
        if (
          hk.toLowerCase() !== "content-security-policy" &&
          hk.toLowerCase() !== "x-frame-options"
        ) {
          res.setHeader(hk, hv);
        }
      }
      res.writeHead(forwardRes.statusCode);
      res.end(forwardRes.body);
    } catch (err: any) {
      if (timer) clearTimeout(timer);
      if (abortFn && inFlightRequests.has(appKey)) {
        inFlightRequests.get(appKey)!.delete(abortFn);
      }
      if (isAborted) return;

      if (err instanceof PayloadTooLargeError) {
        res.writeHead(413, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            error: "QUOTA_EXCEEDED",
            code: "QUOTA_EXCEEDED",
            metric: "request_body_max_mb",
            limit: Math.round(err.maxBytes / (1024 * 1024)),
            message: err.message,
          }),
        );
        return;
      }

      if (err.code === "TIMEOUT") {
        res.writeHead(504, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            error: "QUOTA_EXCEEDED",
            code: "QUOTA_EXCEEDED",
            metric: "request_timeout_s",
            limit: app.manifest?.limits?.request_timeout_s || 30,
            message: err.message,
          }),
        );
        return;
      }

      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({ error: "Bad Gateway", details: err.message || err }),
      );
    }
  });

  // Attach emergency kill switch methods to server instance
  (server as any).suspendApp = async (
    appKey: string,
    _reason = "Emergency suspension",
  ) => {
    const app = accessManager.getApp(appKey);
    if (app) {
      app.status = "suspended";
    }
    // Immediately abort any in-flight requests
    const aborts = inFlightRequests.get(appKey);
    if (aborts) {
      for (const abort of aborts) abort();
      aborts.clear();
    }
    await lifecycleManager.suspend(appKey).catch(() => {});
  };

  (server as any).resumeApp = async (appKey: string) => {
    const app = accessManager.getApp(appKey);
    if (app) {
      app.status = "active";
    }
  };

  (server as any).freezeOrg = async (
    orgId: string,
    _reason = "Emergency freeze",
  ) => {
    // Suspend all apps in access manager for this org
    for (const [key, app] of (accessManager as any).appRegistry.entries()) {
      if (app.organizationId === orgId) {
        app.orgStatus = "suspended";
        app.status = "suspended";
        const aborts = inFlightRequests.get(key);
        if (aborts) {
          for (const abort of aborts) abort();
          aborts.clear();
        }
        await lifecycleManager.suspend(key).catch(() => {});
      }
    }
  };

  (server as any).resumeOrg = async (orgId: string) => {
    for (const [, app] of (accessManager as any).appRegistry.entries()) {
      if (app.organizationId === orgId) {
        app.orgStatus = "active";
        app.status = "active";
      }
    }
  };

  return server;
}
