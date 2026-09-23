/**
 * SandboxRunnerServer
 *
 * Runs on private Sandbox Host EC2 instances.
 * Hosts the SandboxDriver (GVisorDriver in production, DockerDevDriver in dev)
 * and exposes an authenticated internal HTTP interface for Edge Proxy and Control Plane.
 */
import crypto from "node:crypto";
import http from "node:http";
import type {
  SandboxDriver,
  SandboxSpec,
  ForwardRequest,
} from "./interface.js";

/**
 * Constant-time string comparison using SHA-256 digests and crypto.timingSafeEqual.
 * Guarantees fixed 32-byte comparison length regardless of input lengths, preventing timing leaks.
 */
export function timingSafeCompare(a: string, b: string): boolean {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const hashA = crypto.createHash("sha256").update(a).digest();
  const hashB = crypto.createHash("sha256").update(b).digest();
  return crypto.timingSafeEqual(hashA, hashB) && a.length === b.length;
}

/**
 * Validate whether an IP address belongs to the allowed private VPC CIDRs (10.0.0.0/8, 172.16.0.0/12)
 * or local loopback interfaces. Rejects public internet IPs and non-VPC traffic.
 */
export function isVpcCidr(ip: string): boolean {
  if (!ip) return false;
  const cleanIp = ip.replace(/^::ffff:/, "").trim();
  if (cleanIp === "127.0.0.1" || cleanIp === "::1" || cleanIp === "localhost") {
    return true;
  }
  const parts = cleanIp.split(".").map(Number);
  if (parts.length !== 4 || parts.some((n) => isNaN(n) || n < 0 || n > 255)) {
    return false;
  }
  // 10.0.0.0/8
  if (parts[0] === 10) return true;
  // 172.16.0.0/12 (172.16.0.0 - 172.31.255.255)
  if (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) return true;
  return false;
}

export interface SandboxRunnerServerOptions {
  driver: SandboxDriver;
  secret?: string;
  port?: number;
  enforceVpcOnly?: boolean;
}

export function createSandboxRunnerServer(
  options: SandboxRunnerServerOptions,
): http.Server {
  const driver = options.driver;
  const sharedSecret = options.secret || process.env.RUNNER_SHARED_SECRET;

  const server = http.createServer(async (req, res) => {
    // 0. Ingress Network Boundary Check: Enforce VPC CIDR access (defense-in-depth behind UFW)
    const rawIp =
      (req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() ||
      req.socket.remoteAddress ||
      "";
    if (options.enforceVpcOnly && !isVpcCidr(rawIp)) {
      res.writeHead(403, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          error: "VPC_INGRESS_DENIED",
          message: `Access to sandbox runner port 8095 from non-VPC IP '${rawIp}' is prohibited. Allowed only from private VPC CIDRs (10.0.0.0/8, 172.16.0.0/12).`,
        }),
      );
      return;
    }

    // 1. Healthcheck (no auth required for container orchestrators / ALBs)
    if (req.url === "/healthz" && req.method === "GET") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          status: "healthy",
          driver: driver.name,
          timestamp: new Date().toISOString(),
        }),
      );
      return;
    }

    // 2. Authentication check (constant-time token verification)
    if (sharedSecret) {
      const authHeader = (req.headers["authorization"] as string) || "";
      const expected = `Bearer ${sharedSecret}`;
      if (!timingSafeCompare(authHeader, expected)) {
        res.writeHead(401, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            error: "UNAUTHORIZED",
            message: "Invalid runner shared secret",
          }),
        );
        return;
      }
    }

    // Helper to read JSON request body
    const readBody = (): Promise<any> =>
      new Promise((resolve, reject) => {
        let data = "";
        req.on("data", (chunk) => (data += chunk));
        req.on("end", () => {
          if (!data) return resolve({});
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            reject(new Error("Invalid JSON body"));
          }
        });
        req.on("error", reject);
      });

    try {
      const url = new URL(
        req.url || "/",
        `http://${req.headers.host || "localhost"}`,
      );
      const pathname = url.pathname;

      // POST /v1/sandboxes/start
      if (pathname === "/v1/sandboxes/start" && req.method === "POST") {
        const spec: SandboxSpec = await readBody();
        // Multi-tenant authorization guard: caller organization must match app's owning organization
        const callerOrg =
          (req.headers["x-caller-org-id"] as string) ||
          (spec as any).callerOrgId;
        const appOwnerOrg = (spec as any).organizationId || (spec as any).orgId;
        if (callerOrg && appOwnerOrg && callerOrg !== appOwnerOrg) {
          res.writeHead(403, { "Content-Type": "application/json" });
          res.end(
            JSON.stringify({
              error: "CROSS_TENANT_ACCESS_DENIED",
              message: `Caller from organization '${callerOrg}' is forbidden from launching capsule belonging to organization '${appOwnerOrg}'.`,
            }),
          );
          return;
        }
        const instance = await driver.start(spec);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify(instance));
        return;
      }

      const match = pathname.match(
        /^\/v1\/sandboxes\/([^/]+)\/(stop|suspend|resume|status|logs|forward|recover|destroy)$/,
      );
      if (match) {
        const instanceId = decodeURIComponent(match[1]);
        const action = match[2];

        if (action === "destroy" && req.method === "POST") {
          await driver.destroy(instanceId);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ success: true }));
          return;
        }

        if (action === "status" && req.method === "GET") {
          const status = await driver.status(instanceId);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ status }));
          return;
        }

        if (action === "logs" && req.method === "GET") {
          const tail = url.searchParams.get("tail")
            ? Number(url.searchParams.get("tail"))
            : undefined;
          const since = url.searchParams.get("since")
            ? new Date(url.searchParams.get("since")!)
            : undefined;
          const logs = await driver.logs(instanceId, { tail, since });
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ logs }));
          return;
        }

        if (action === "stop" && req.method === "POST") {
          await driver.stop(instanceId);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ success: true }));
          return;
        }

        if (action === "suspend" && req.method === "POST") {
          await driver.suspend(instanceId);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ success: true }));
          return;
        }

        if (action === "resume" && req.method === "POST") {
          await driver.resume(instanceId);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ success: true }));
          return;
        }

        if (action === "recover" && req.method === "POST") {
          const instance = await driver.recover(instanceId);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify(instance));
          return;
        }

        if (action === "forward" && req.method === "POST") {
          const payload = await readBody();
          const forwardReq: ForwardRequest = {
            method: payload.method,
            path: payload.path,
            headers: payload.headers,
            body: payload.isBase64
              ? Buffer.from(payload.body || "", "base64")
              : payload.body,
          };
          const forwardRes = await driver.forwardRequest(
            instanceId,
            forwardReq,
          );
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify(forwardRes));
          return;
        }
      }

      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          error: "NOT_FOUND",
          message: `Route ${req.method} ${pathname} not found`,
        }),
      );
    } catch (err: any) {
      const isUnavailable =
        err.code === "SANDBOX_UNAVAILABLE" ||
        err.message?.includes("is not configured in Docker daemon") ||
        err.message?.includes("not configured") ||
        err.message?.includes("SANDBOX_UNAVAILABLE");

      const statusCode = isUnavailable ? 503 : 500;
      res.writeHead(statusCode, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          error: isUnavailable ? "SANDBOX_UNAVAILABLE" : "RUNNER_ERROR",
          message: err.message,
          code: err.code || (isUnavailable ? "SANDBOX_UNAVAILABLE" : undefined),
        }),
      );
    }
  });

  return server;
}
