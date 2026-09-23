/**
 * SandboxRunnerServer
 *
 * Runs on private Sandbox Host EC2 instances.
 * Hosts the SandboxDriver (GVisorDriver in production, DockerDevDriver in dev)
 * and exposes an authenticated internal HTTP interface for Edge Proxy and Control Plane.
 */
import http from "node:http";
import type {
  SandboxDriver,
  SandboxSpec,
  ForwardRequest,
} from "./interface.js";

export interface SandboxRunnerServerOptions {
  driver: SandboxDriver;
  secret?: string;
  port?: number;
}

export function createSandboxRunnerServer(
  options: SandboxRunnerServerOptions,
): http.Server {
  const driver = options.driver;
  const sharedSecret = options.secret || process.env.RUNNER_SHARED_SECRET;

  const server = http.createServer(async (req, res) => {
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

    // 2. Authentication check
    if (sharedSecret) {
      const authHeader = req.headers["authorization"] || "";
      const expected = `Bearer ${sharedSecret}`;
      if (authHeader !== expected) {
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
