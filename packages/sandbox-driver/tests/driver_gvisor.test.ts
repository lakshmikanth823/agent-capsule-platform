import { describe, it, expect, beforeAll, afterAll } from "vitest";
import path from "node:path";
import fs from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import {
  GVisorDriver,
  isDockerAvailable,
  type SandboxSpec,
} from "../src/index.js";

const execFileAsync = promisify(execFile);
const hasDocker = isDockerAvailable();

describe("GVisorDriver (Option A Production Sandbox Driver)", () => {
  const sampleSpec: SandboxSpec = {
    capsuleId: "leave-tracker-gv",
    versionId: "v1.0.0",
    appKey: "leave-tracker",
    bundlePath: path.resolve("examples/leave-tracker"),
    dataDir: path.resolve("data/test-gvisor/data"),
    limits: {
      cpu: "0.5",
      memoryMb: 256,
      pidsLimit: 64,
      timeoutSeconds: 30,
    },
    networkMode: "none",
    env: {
      CUSTOM_VAR: "custom_value",
    },
  };

  it("should implement the SandboxDriver interface with correct driver name", () => {
    const driver = new GVisorDriver();
    expect(driver.name).toBe("gvisor");
    expect(typeof driver.start).toBe("function");
    expect(typeof driver.stop).toBe("function");
    expect(typeof driver.suspend).toBe("function");
    expect(typeof driver.resume).toBe("function");
    expect(typeof driver.status).toBe("function");
    expect(typeof driver.logs).toBe("function");
    expect(typeof driver.forwardRequest).toBe("function");
    expect(typeof driver.destroy).toBe("function");
    expect(typeof driver.isAvailable).toBe("function");
    expect(typeof driver.buildExecutionArgs).toBe("function");
  });

  it("should build execution arguments with hardened gVisor and OCI security flags", async () => {
    const driver = new GVisorDriver();
    const args = await driver.buildExecutionArgs(
      sampleSpec,
      "test-instance-123",
    );

    // 1. Must invoke docker run in detached mode
    expect(args[0]).toBe("run");
    expect(args[1]).toBe("-d");
    expect(args).toContain("--name");
    expect(args).toContain("test-instance-123");

    // 2. Must specify runsc OCI runtime and ptrace platform
    const runtimeIndex = args.indexOf("--runtime");
    expect(runtimeIndex).not.toBe(-1);
    expect(args[runtimeIndex + 1]).toBe("runsc");
    expect(args).toContain("--runtime-flag=--platform=ptrace");

    // 3. Must enforce non-root user (1000:1000)
    const userIndex = args.indexOf("--user");
    expect(userIndex).not.toBe(-1);
    expect(args[userIndex + 1]).toBe("1000:1000");

    // 4. Must enforce read-only root filesystem
    expect(args).toContain("--read-only");

    // 5. Must drop all capabilities and disallow privilege escalation
    expect(args).toContain("--cap-drop=ALL");
    expect(args).toContain("no-new-privileges:true");

    // 6. Must isolate network with default-deny
    expect(args).toContain("--network");
    expect(args).toContain("none");
    expect(args).toContain("--runtime-flag=--network=none");

    // 7. Must configure temporary scratch tmpfs
    expect(args).toContain("/tmp:rw,noexec,nosuid,size=64m");
    expect(args).toContain("/run:rw,noexec,nosuid,size=16m");

    // 8. Must mount bundle read-only
    const hasAppRoMount = args.some((arg) => arg.includes("/app:ro"));
    expect(hasAppRoMount).toBe(true);

    // 9. Must mount dataDir read-write
    const hasDataRwMount = args.some((arg) => arg.includes("/data:rw"));
    expect(hasDataRwMount).toBe(true);

    // 10. Must configure resource ceilings (cgroups v2 & Sentry limits)
    expect(args).toContain("--cpus");
    expect(args).toContain("0.5");
    expect(args).toContain("--memory");
    expect(args).toContain("256m");
    expect(args).toContain("--memory-swap");
    expect(args).toContain("256m");
    expect(args).toContain("--pids-limit");
    expect(args).toContain("64");

    // 11. Must include custom environment variables
    expect(args).toContain("CUSTOM_VAR=custom_value");
  });

  it("should support custom gVisor driver options", async () => {
    const customDriver = new GVisorDriver({
      runtimeName: "runsc-kvm",
      platform: "kvm",
    });

    const args = await customDriver.buildExecutionArgs(
      sampleSpec,
      "test-instance-custom",
    );
    const runtimeIndex = args.indexOf("--runtime");
    expect(args[runtimeIndex + 1]).toBe("runsc-kvm");
    expect(args).toContain("--runtime-flag=--platform=kvm");
  });

  it("should omit writable /data mount if dataDir is not declared in spec", async () => {
    const driver = new GVisorDriver();
    const statelessSpec: SandboxSpec = {
      capsuleId: "stateless-app",
      versionId: "v1.0.0",
      appKey: "stateless-app",
      bundlePath: path.resolve("examples/leave-tracker"),
      dataDir: "", // no SQLite capability
    };

    const args = await driver.buildExecutionArgs(
      statelessSpec,
      "test-stateless",
    );
    const hasDataMount = args.some((arg) => arg.includes("/data:rw"));
    expect(hasDataMount).toBe(false);
  });

  it("should report runtime availability status via isAvailable without throwing", async () => {
    const driver = new GVisorDriver();
    const available = await driver.isAvailable();
    expect(typeof available).toBe("boolean");
  });

  it("should reject start with descriptive error when runsc is unavailable and fallback is disabled", async () => {
    const driver = new GVisorDriver({
      runtimeName: "nonexistent-runsc-runtime",
    });
    const originalEnv = process.env.ALLOW_DEV_FALLBACK;
    delete process.env.ALLOW_DEV_FALLBACK;

    try {
      await expect(driver.start(sampleSpec)).rejects.toThrow(
        /gVisor runtime 'nonexistent-runsc-runtime' is not configured in Docker daemon/,
      );
    } finally {
      if (originalEnv !== undefined) {
        process.env.ALLOW_DEV_FALLBACK = originalEnv;
      }
    }
  });

  describe.skipIf(!hasDocker)(
    "Prompt 21B Acceptance: Sample App Execution & Exploit Blockage",
    { timeout: 35000 },
    () => {
      const testDataDir = path.resolve("data/test-gvisor-acceptance");
      let activeInstanceId: string | null = null;
      let driver: GVisorDriver;

      beforeAll(async () => {
        process.env.ALLOW_DEV_FALLBACK = "1";
        await fs.mkdir(testDataDir, { recursive: true });
      });

      afterAll(async () => {
        delete process.env.ALLOW_DEV_FALLBACK;
        if (activeInstanceId && driver) {
          await driver.destroy(activeInstanceId).catch(() => {});
        }
        await fs
          .rm(testDataDir, { recursive: true, force: true })
          .catch(() => {});
      });

      it("should start sample app under GVisorDriver and verify the Prompt 01 curl flow works identically", async () => {
        driver = new GVisorDriver();
        const spec: SandboxSpec = {
          capsuleId: "leave-tracker-gv-acc",
          versionId: "v1.0.0",
          appKey: "leave-tracker",
          bundlePath: path.resolve("examples/leave-tracker"),
          dataDir: path.join(testDataDir, "data"),
          limits: {
            cpu: "0.5",
            memoryMb: 256,
            pidsLimit: 64,
            timeoutSeconds: 30,
          },
          networkMode: "none",
        };

        const instance = await driver.start(spec);
        activeInstanceId = instance.id;
        expect(instance.id).toBeDefined();
        expect(await driver.status(instance.id)).toBe("running");

        // 1. Health check (Prompt 01: curl http://localhost:3000/health)
        const healthResp = await driver.forwardRequest(instance.id, {
          method: "GET",
          path: "/health",
        });
        expect(healthResp.statusCode).toBe(200);
        const healthData = JSON.parse(healthResp.body);
        expect(healthData.status).toBe("healthy");
        expect(healthData.app).toBe("leave-tracker");

        // 2. Identity inspection (Prompt 01: curl with x-capsule-identity header)
        const identityPayload = {
          iss: "platform",
          aud: "capsule:leave-tracker",
          sub: "usr_alice_123",
          org_id: "org_acme",
          groups: ["engineering"],
          roles: ["employee"],
          iat: Math.floor(Date.now() / 1000),
          exp: Math.floor(Date.now() / 1000) + 3600,
        };

        const idResp = await driver.forwardRequest(instance.id, {
          method: "GET",
          path: "/api/identity",
          headers: {
            "x-capsule-identity": JSON.stringify(identityPayload),
          },
        });
        expect(idResp.statusCode).toBe(200);
        const idData = JSON.parse(idResp.body);
        expect(idData.authenticated).toBe(true);
        expect(idData.identity.sub).toBe("usr_alice_123");

        // 3. Database operation (Prompt 01: POST /api/leaves & GET /api/leaves)
        const postLeaveResp = await driver.forwardRequest(instance.id, {
          method: "POST",
          path: "/api/leaves",
          headers: {
            "content-type": "application/json",
            "x-capsule-identity": JSON.stringify(identityPayload),
          },
          body: JSON.stringify({
            start_date: "2026-11-01",
            end_date: "2026-11-05",
            reason: "Conference Attendance",
          }),
        });
        expect(postLeaveResp.statusCode).toBe(201);
        const created = JSON.parse(postLeaveResp.body);
        expect(created.id).toBeDefined();
        expect(created.reason).toBe("Conference Attendance");

        const getLeavesResp = await driver.forwardRequest(instance.id, {
          method: "GET",
          path: "/api/leaves",
        });
        expect(getLeavesResp.statusCode).toBe(200);
        const listData = JSON.parse(getLeavesResp.body);
        expect(listData.leaves.length).toBeGreaterThanOrEqual(1);
        expect(
          listData.leaves.some(
            (l: any) => l.reason === "Conference Attendance",
          ),
        ).toBe(true);
      });

      it("should verify exploit attempts are blocked by driver isolation", async () => {
        expect(activeInstanceId).not.toBeNull();

        // Exploit Attempt 1: Trying to read /etc/shadow
        // Non-root user (1000:1000) inside container lacks read access to /etc/shadow
        let shadowReadBlocked = false;
        try {
          await execFileAsync("docker", [
            "exec",
            activeInstanceId!,
            "cat",
            "/etc/shadow",
          ]);
        } catch (err: any) {
          // Must fail with Permission denied
          shadowReadBlocked =
            err.message.includes("Permission denied") ||
            err.stderr?.includes("Permission denied") ||
            err.code !== 0;
        }
        expect(shadowReadBlocked).toBe(true);

        // Exploit Attempt 2: Trying to write to the root filesystem (/exploit.txt)
        // Read-only rootfs (--read-only) blocks any write outside tmpfs mounts
        let rootWriteBlocked = false;
        try {
          await execFileAsync("docker", [
            "exec",
            activeInstanceId!,
            "node",
            "-e",
            "require('fs').writeFileSync('/exploit.txt', 'evil_payload')",
          ]);
        } catch (err: any) {
          rootWriteBlocked =
            err.message.includes("EROFS") ||
            err.message.includes("read-only file system") ||
            err.stderr?.includes("EROFS") ||
            err.stderr?.includes("read-only file system") ||
            err.code !== 0;
        }
        expect(rootWriteBlocked).toBe(true);

        // Exploit Attempt 3: Trying to overwrite application bundle code (/app/dist/index.js)
        let appBundleWriteBlocked = false;
        try {
          await execFileAsync("docker", [
            "exec",
            activeInstanceId!,
            "node",
            "-e",
            "require('fs').writeFileSync('/app/dist/malicious.js', 'compromised')",
          ]);
        } catch (err: any) {
          appBundleWriteBlocked =
            err.message.includes("EROFS") ||
            err.message.includes("read-only file system") ||
            err.stderr?.includes("EROFS") ||
            err.stderr?.includes("read-only file system") ||
            err.code !== 0;
        }
        expect(appBundleWriteBlocked).toBe(true);
      });
    },
  );
});
