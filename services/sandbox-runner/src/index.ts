/**
 * Capsule Sandbox Runner Service
 *
 * Runs strictly on dedicated, private Sandbox Host instances.
 * Hosts GVisorDriver (runsc) with Docker socket access, exposing an internal
 * authenticated API for Edge Proxy and Control Plane over the private VPC.
 */
import {
  createSandboxRunnerServer,
  GVisorDriver,
  DockerDevDriver,
  DevMockSandboxDriver,
  type SandboxDriver,
} from "@capsule/sandbox-driver";

const port = Number(process.env.PORT) || 8095;
const secret = process.env.RUNNER_SHARED_SECRET;
const isProduction =
  process.env.NODE_ENV === "production" ||
  process.env.PLATFORM_ENV === "production";
const driverType =
  process.env.SANDBOX_DRIVER || (isProduction ? "gvisor" : "mock");

if (isProduction && !secret) {
  throw new Error(
    "SECURITY VIOLATION: RUNNER_SHARED_SECRET must be set in production to protect sandbox host runner.",
  );
}

let driver: SandboxDriver;
if (driverType === "gvisor") {
  driver = new GVisorDriver();
} else if (driverType === "docker") {
  driver = new DockerDevDriver();
} else {
  if (isProduction && !process.env.ALLOW_DEV_FALLBACK) {
    throw new Error(
      "FATAL: Mock sandbox driver is forbidden in production environment. Configure GVisorDriver.",
    );
  }
  driver = new DevMockSandboxDriver();
}

const server = createSandboxRunnerServer({
  driver,
  secret,
  port,
});

server.listen(port, "0.0.0.0", () => {
  console.log(
    `[sandbox-runner] Listening on port ${port} (driver: ${driver.name}, production: ${isProduction})`,
  );
});

export { server };
