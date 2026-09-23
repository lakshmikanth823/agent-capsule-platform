import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { AddressInfo } from "node:net";
import http from "node:http";
import {
  RemoteSandboxDriver,
  createSandboxRunnerServer,
  DevMockSandboxDriver,
  type SandboxSpec,
} from "../src/index.js";

describe("RemoteSandboxDriver & SandboxRunnerServer", () => {
  let server: http.Server;
  let serverPort: number;
  let mockDriver: DevMockSandboxDriver;
  let remoteDriver: RemoteSandboxDriver;
  const testSecret = "test-runner-shared-secret-12345";

  beforeAll(async () => {
    mockDriver = new DevMockSandboxDriver();
    server = createSandboxRunnerServer({
      driver: mockDriver,
      secret: testSecret,
    });

    await new Promise<void>((resolve) => {
      server.listen(0, "127.0.0.1", () => {
        serverPort = (server.address() as AddressInfo).port;
        resolve();
      });
    });

    remoteDriver = new RemoteSandboxDriver({
      runnerUrl: `http://127.0.0.1:${serverPort}`,
      secret: testSecret,
    });
  });

  afterAll(async () => {
    await new Promise((resolve) => server.close(resolve));
  });

  it("checks availability via healthz endpoint", async () => {
    const avail = await remoteDriver.isAvailable();
    expect(avail).toBe(true);
  });

  it("rejects unauthorized client requests when secret is invalid", async () => {
    const unauthDriver = new RemoteSandboxDriver({
      runnerUrl: `http://127.0.0.1:${serverPort}`,
      secret: "wrong-secret",
    });

    const spec: SandboxSpec = {
      capsuleId: "cap-test-1",
      versionId: "ver-1",
      appKey: "test-app",
      bundlePath: "/tmp/fake",
      dataDir: "/tmp/data",
    };

    await expect(unauthDriver.start(spec)).rejects.toThrow(
      /Invalid runner shared secret|HTTP 401/,
    );
  });

  it("proxies start, forward, status, and stop operations to remote runner", async () => {
    const spec: SandboxSpec = {
      capsuleId: "cap-test-2",
      versionId: "ver-1",
      appKey: "test-app-2",
      bundlePath: "/tmp/fake",
      dataDir: "/tmp/data",
    };

    // 1. Start sandbox
    const instance = await remoteDriver.start(spec);
    expect(instance.id).toBeDefined();
    expect(instance.status).toBe("running");

    // 2. Query status
    const status = await remoteDriver.status(instance.id);
    expect(status).toBe("running");

    // 3. Forward request
    const res = await remoteDriver.forwardRequest(instance.id, {
      method: "GET",
      path: "/health",
    });
    expect(res.statusCode).toBe(200);

    // 4. Suspend and resume
    await remoteDriver.suspend(instance.id);
    await remoteDriver.resume(instance.id);

    // 5. Query logs
    const logs = await remoteDriver.logs(instance.id);
    expect(Array.isArray(logs)).toBe(true);

    // 6. Stop
    await remoteDriver.stop(instance.id);
  });

  it("propagates HTTP 503 SANDBOX_UNAVAILABLE when remote gVisor runtime is missing", async () => {
    const failingDriver = {
      name: "gvisor",
      async isAvailable() {
        return false;
      },
      async start() {
        const err = new Error(
          "[GVisorDriver] gVisor runtime 'runsc' is not configured in Docker daemon.",
        );
        (err as any).code = "SANDBOX_UNAVAILABLE";
        throw err;
      },
      async stop() {},
      async suspend() {},
      async resume() {},
      async status() {
        return "stopped" as const;
      },
      async logs() {
        return [];
      },
      async forwardRequest() {
        return { statusCode: 500, headers: {}, body: "" };
      },
      async recover() {
        throw new Error("recover failed");
      },
    };

    const failingServer = createSandboxRunnerServer({
      driver: failingDriver as any,
      secret: "fail-secret",
    });

    await new Promise<void>((resolve) => failingServer.listen(0, resolve));
    const failPort = (failingServer.address() as AddressInfo).port;

    try {
      const client = new RemoteSandboxDriver({
        runnerUrl: `http://127.0.0.1:${failPort}`,
        secret: "fail-secret",
      });

      const spec: SandboxSpec = {
        capsuleId: "cap-unavail",
        versionId: "ver-1",
        appKey: "unavail",
        bundlePath: "/tmp",
        dataDir: "/tmp",
      };

      try {
        await client.start(spec);
        expect.unreachable();
      } catch (err: any) {
        expect(err.code).toBe("SANDBOX_UNAVAILABLE");
        expect(err.message).toContain("not configured");
      }
    } finally {
      await new Promise((resolve) => failingServer.close(resolve));
    }
  });
});
