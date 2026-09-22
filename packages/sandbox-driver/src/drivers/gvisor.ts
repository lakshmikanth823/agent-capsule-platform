/**
 * GVisorDriver (Production Multi-Tenant Sandbox Driver)
 *
 * Implements PRD Security Invariants 1 & 9, PRD FR-001, FR-008, TRD Section 9.
 *
 * Uses gVisor's `runsc` runtime to enforce a strict user-space kernel boundary:
 * - Sentry: Re-implements Linux syscalls in memory-safe Go; untrusted code never touches host kernel.
 * - Gofer: Mediates all filesystem access.
 * - Netstack: User-space TCP/IP stack enforcing default-deny (--network=none) and proxy-only routing.
 * - Hardened OCI execution: Non-root user (1000:1000), read-only rootfs, dropped capabilities,
 *   no-new-privileges, restricted tmpfs mounts, cgroups v2 resource ceilings.
 */
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import fs from "node:fs/promises";
import type {
  SandboxDriver,
  SandboxSpec,
  SandboxInstance,
  SandboxStatus,
  LogOptions,
  ForwardRequest,
  ForwardResponse,
  ColdStartStats,
} from "../interface.js";

const execFileAsync = promisify(execFile);

export interface GVisorDriverOptions {
  runtimeName?: string;
  platform?: "ptrace" | "kvm";
  networkMode?: "none" | "bridge";
}

export class GVisorDriver implements SandboxDriver {
  readonly name = "gvisor";
  private runtimeName: string;
  private platform: "ptrace" | "kvm";
  private instances = new Map<string, SandboxInstance>();
  private coldStartSamples: number[] = [];

  constructor(options: GVisorDriverOptions = {}) {
    this.runtimeName =
      options.runtimeName || process.env.GVISOR_RUNTIME || "runsc";
    this.platform =
      options.platform ||
      (process.env.GVISOR_PLATFORM as "ptrace" | "kvm") ||
      "ptrace";
  }

  private normalizePathForDocker(p: string): string {
    return path.resolve(p).replace(/\\/g, "/");
  }

  private parseCpuLimit(cpu?: string): string {
    if (!cpu || cpu === "small") return "0.5";
    if (cpu === "medium") return "1.0";
    if (cpu === "large") return "2.0";
    return cpu;
  }

  /**
   * Check whether the gVisor OCI runtime (runsc) is available in the local Docker/containerd daemon.
   */
  async isAvailable(): Promise<boolean> {
    try {
      const { stdout } = await execFileAsync("docker", [
        "info",
        "--format",
        "{{json .Runtimes}}",
      ]);
      const runtimes = JSON.parse(stdout.trim() || "{}");
      return (
        Boolean(runtimes[this.runtimeName]) ||
        Boolean(runtimes["runsc"]) ||
        Boolean(runtimes["io.containerd.runsc.v1"])
      );
    } catch {
      return false;
    }
  }

  /**
   * Constructs the hardened Docker/runsc CLI execution arguments for a sandbox specification.
   * Useful for unit testing, dry-run validation, and security auditing.
   */
  async buildExecutionArgs(
    spec: SandboxSpec,
    instanceId: string,
  ): Promise<string[]> {
    const cpuLimit = this.parseCpuLimit(spec.limits?.cpu);
    const memoryMb = spec.limits?.memoryMb || 256;
    const pidsLimit = spec.limits?.pidsLimit || 64;
    const networkMode = spec.networkMode || "none";

    const normalizedAppDir = this.normalizePathForDocker(spec.bundlePath);

    const dbMaxSizeMb =
      spec.manifest?.capabilities?.db?.max_size_mb ||
      spec.manifest?.limits?.db_max_mb ||
      50;

    const dockerArgs = [
      "run",
      "-d",
      "--name",
      instanceId,
      // 1. gVisor Sentry OCI Runtime
      "--runtime",
      this.runtimeName,
      // Pass gVisor platform configuration
      `--runtime-flag=--platform=${this.platform}`,
      // 2. Non-root user (node user UID 1000 in node:22-alpine)
      "--user",
      "1000:1000",
      // 3. Read-only root filesystem
      "--read-only",
      // 4. Dropped Linux capabilities & prevent privilege escalation
      "--cap-drop=ALL",
      "--security-opt",
      "no-new-privileges:true",
      // 5. Temporary writable scratch spaces (noexec, nosuid, bounded size)
      "--tmpfs",
      "/tmp:rw,noexec,nosuid,size=64m",
      "--tmpfs",
      "/run:rw,noexec,nosuid,size=16m",
      // 6. Application code bundle mounted strictly read-only
      "-v",
      `${normalizedAppDir}:/app:ro`,
    ];

    // Mount writable /data only if dataDir is provided (sqlite / blobs capability)
    if (spec.dataDir) {
      const normalizedDataDir = this.normalizePathForDocker(spec.dataDir);
      dockerArgs.push("-v", `${normalizedDataDir}:/data:rw`);
    }

    // 7. Per-instance resource limits (cgroups v2 + Sentry memory limits)
    dockerArgs.push(
      "--cpus",
      cpuLimit,
      "--memory",
      `${memoryMb}m`,
      "--memory-swap",
      `${memoryMb}m`,
      "--pids-limit",
      String(pidsLimit),
    );

    // 8. User-space Netstack network isolation
    dockerArgs.push("--network", networkMode);
    if (networkMode === "none") {
      dockerArgs.push("--runtime-flag=--network=none");
    }

    // 9. Environment variables and runtime configuration
    dockerArgs.push(
      "-w",
      "/app",
      "-e",
      "NODE_ENV=production",
      "-e",
      "PORT=3000",
      "-e",
      `CAPSULE_ID=${spec.capsuleId}`,
      "-e",
      `APP_ID=${spec.appKey}`,
    );

    if (spec.dataDir) {
      dockerArgs.push(
        "-e",
        "DATABASE_PATH=/data/app.sqlite",
        "-e",
        "CAPSULE_BLOB_DIR=/data/blobs",
        "-e",
        `DB_MAX_SIZE_MB=${dbMaxSizeMb}`,
      );
    }

    if (process.env.CAPSULE_IDENTITY_SECRET) {
      dockerArgs.push(
        "-e",
        `CAPSULE_IDENTITY_SECRET=${process.env.CAPSULE_IDENTITY_SECRET}`,
      );
    }

    if (spec.env) {
      for (const [key, value] of Object.entries(spec.env)) {
        dockerArgs.push("-e", `${key}=${value}`);
      }
    }

    if (networkMode === "bridge" && spec.port) {
      dockerArgs.push("-p", `127.0.0.1:${spec.port}:3000`);
    }

    // Determine entrypoint: dist/index.js, src/index.js, or index.js
    let entrypoint = "dist/index.js";
    try {
      await fs.access(path.join(spec.bundlePath, "dist", "index.js"));
      entrypoint = "dist/index.js";
    } catch {
      try {
        await fs.access(path.join(spec.bundlePath, "src", "index.js"));
        entrypoint = "src/index.js";
      } catch {
        entrypoint = "index.js";
      }
    }

    dockerArgs.push("node:22-alpine", "node", entrypoint);
    return dockerArgs;
  }

  async start(spec: SandboxSpec): Promise<SandboxInstance> {
    const instanceId = `capsule-gv-${spec.capsuleId}-${Date.now()}`;

    // Ensure data directory exists on host if dataDir is specified
    if (spec.dataDir) {
      await fs.mkdir(spec.dataDir, { recursive: true });
      await fs.mkdir(path.join(spec.dataDir, "blobs"), { recursive: true });
      try {
        await fs.chmod(spec.dataDir, 0o777);
        await fs.chmod(path.join(spec.dataDir, "blobs"), 0o777);
        const parentDir = path.dirname(spec.dataDir);
        await fs.chmod(parentDir, 0o777).catch(() => {});
      } catch {}
    }

    const dockerArgs = await this.buildExecutionArgs(spec, instanceId);

    // Verify runtime availability before spawning
    const available = await this.isAvailable();
    if (!available && !process.env.ALLOW_DEV_FALLBACK) {
      throw new Error(
        `[GVisorDriver] gVisor runtime '${this.runtimeName}' is not configured in Docker daemon. ` +
          `Install gVisor runsc (https://gvisor.dev/docs/user_guide/install/) and register it in /etc/docker/daemon.json, ` +
          `or set ALLOW_DEV_FALLBACK=1 for local development testing.`,
      );
    }

    // If fallback is enabled in dev environment, replace --runtime runsc with default runc
    if (!available && process.env.ALLOW_DEV_FALLBACK) {
      const rtIndex = dockerArgs.indexOf("--runtime");
      if (rtIndex !== -1) {
        dockerArgs.splice(rtIndex, 2);
      }
      const flagIndices = dockerArgs
        .map((arg, idx) => (arg.startsWith("--runtime-flag") ? idx : -1))
        .filter((idx) => idx !== -1)
        .reverse();
      for (const idx of flagIndices) {
        dockerArgs.splice(idx, 1);
      }
    }

    const startTimestamp = Date.now();
    try {
      await execFileAsync("docker", dockerArgs);

      const now = new Date();
      const instance: SandboxInstance = {
        id: instanceId,
        capsuleId: spec.capsuleId,
        versionId: spec.versionId,
        status: "running",
        spec,
        assignedPort: spec.port,
        createdAt: now,
        startedAt: now,
        lastActiveAt: now,
      };
      this.instances.set(instanceId, instance);

      // Await container readiness
      await this.waitForReady(instanceId, 15000);
      const coldStartMs = Date.now() - startTimestamp;
      instance.coldStartMs = coldStartMs;
      this.recordColdStart(coldStartMs);

      return instance;
    } catch (err: any) {
      let containerLogs = "";
      try {
        const logsArr = await this.logs(instanceId);
        containerLogs = logsArr.join("\n");
      } catch {}
      await this.destroy(instanceId).catch(() => {});
      throw new Error(
        `Failed to start gVisor sandbox ${instanceId}: ${err.message || err}. Container logs: ${containerLogs}`,
      );
    }
  }

  private async waitForReady(
    instanceId: string,
    timeoutMs: number,
  ): Promise<void> {
    const startTime = Date.now();
    while (Date.now() - startTime < timeoutMs) {
      try {
        const resp = await this.forwardRequest(instanceId, {
          method: "GET",
          path: "/health",
        });
        if (resp.statusCode === 200) {
          return;
        }
      } catch {
        // Retry
      }
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    throw new Error(
      `gVisor Sandbox ${instanceId} failed to become ready within ${timeoutMs}ms.`,
    );
  }

  async stop(instanceId: string): Promise<void> {
    try {
      await execFileAsync("docker", ["stop", "-t", "2", instanceId]);
      const inst = this.instances.get(instanceId);
      if (inst) inst.status = "stopped";
    } catch (err: any) {
      throw new Error(
        `Failed to stop gVisor sandbox ${instanceId}: ${err.message}`,
      );
    }
  }

  async suspend(instanceId: string): Promise<void> {
    try {
      // Fast pause via cgroups v2 freezer
      await execFileAsync("docker", ["pause", instanceId]);
      const inst = this.instances.get(instanceId);
      if (inst) inst.status = "suspended";
    } catch (err: any) {
      throw new Error(
        `Failed to suspend gVisor sandbox ${instanceId}: ${err.message}`,
      );
    }
  }

  async resume(instanceId: string): Promise<void> {
    try {
      // Fast unpause via cgroups v2 freezer
      await execFileAsync("docker", ["unpause", instanceId]);
      const inst = this.instances.get(instanceId);
      if (inst) {
        inst.status = "running";
        inst.lastActiveAt = new Date();
      }
    } catch (err: any) {
      throw new Error(
        `Failed to resume gVisor sandbox ${instanceId}: ${err.message}`,
      );
    }
  }

  async status(instanceId: string): Promise<SandboxStatus> {
    try {
      const { stdout } = await execFileAsync("docker", [
        "inspect",
        "--format",
        "{{json .State}}",
        instanceId,
      ]);
      const state = JSON.parse(stdout.trim());

      let status: SandboxStatus = "stopped";
      if (state.Paused) {
        status = "suspended";
      } else if (state.Running) {
        status = "running";
      } else if (
        state.OOMKilled ||
        (state.ExitCode !== 0 &&
          state.ExitCode !== 143 &&
          state.ExitCode !== 137)
      ) {
        status = "crashed";
      } else {
        status = "stopped";
      }

      const inst = this.instances.get(instanceId);
      if (inst) inst.status = status;
      return status;
    } catch {
      return "stopped";
    }
  }

  async logs(instanceId: string, options?: LogOptions): Promise<string[]> {
    const args = ["logs"];
    if (options?.tail) {
      args.push("--tail", String(options.tail));
    }
    args.push(instanceId);

    try {
      const { stdout, stderr } = await execFileAsync("docker", args);
      const output = (stdout + "\n" + stderr).trim();
      return output ? output.split("\n") : [];
    } catch (err: any) {
      throw new Error(
        `Failed to read logs for gVisor sandbox ${instanceId}: ${err.message}`,
      );
    }
  }

  async forwardRequest(
    instanceId: string,
    req: ForwardRequest,
  ): Promise<ForwardResponse> {
    const inst = this.instances.get(instanceId);
    if (!inst)
      throw new Error(`gVisor Sandbox ${instanceId} is not tracked by driver.`);

    inst.lastActiveAt = new Date();

    const payload = JSON.stringify({
      method: req.method,
      path: req.path,
      headers: req.headers || {},
      body: req.body || "",
    });

    const bridgeScript =
      "const http=require('http');const reqData=JSON.parse(process.argv[1]);const options={hostname:'127.0.0.1',port:3000,path:reqData.path,method:reqData.method,headers:reqData.headers};const clientReq=http.request(options,(res)=>{let body='';res.on('data',d=>body+=d);res.on('end',()=>{console.log(JSON.stringify({statusCode:res.statusCode,headers:res.headers,body}));});});clientReq.on('error',(e)=>{console.error('BRIDGE_ERROR:'+e.message);process.exit(1);});if(reqData.body)clientReq.write(reqData.body);clientReq.end();";

    try {
      const { stdout } = await execFileAsync("docker", [
        "exec",
        "-i",
        instanceId,
        "node",
        "-e",
        bridgeScript,
        payload,
      ]);

      const result = JSON.parse(stdout.trim());
      return {
        statusCode: result.statusCode,
        headers: result.headers,
        body: result.body,
      };
    } catch (err: any) {
      throw new Error(
        `Failed to forward HTTP request to gVisor sandbox ${instanceId}: ${err.message}`,
      );
    }
  }

  async recover(instanceId: string): Promise<SandboxInstance> {
    const inst = this.instances.get(instanceId);
    if (!inst) {
      throw new Error(`Cannot recover unknown gVisor sandbox: ${instanceId}`);
    }
    await this.destroy(instanceId).catch(() => {});
    return this.start(inst.spec);
  }

  async destroy(instanceId: string): Promise<void> {
    try {
      await execFileAsync("docker", ["rm", "-f", instanceId]);
    } catch {
      // Ignore if already removed
    } finally {
      this.instances.delete(instanceId);
    }
  }

  /**
   * Record a cold-start measurement sample (ms).
   */
  recordColdStart(durationMs: number): void {
    if (durationMs >= 0) {
      this.coldStartSamples.push(durationMs);
    }
  }

  /**
   * Computes summary metrics for sandbox cold starts including p50, p90, p95, p99.
   */
  getColdStartStats(): ColdStartStats {
    if (this.coldStartSamples.length === 0) {
      return {
        count: 0,
        min: 0,
        max: 0,
        avg: 0,
        p50: 0,
        p90: 0,
        p95: 0,
        p99: 0,
      };
    }

    const sorted = [...this.coldStartSamples].sort((a, b) => a - b);
    const count = sorted.length;
    const sum = sorted.reduce((acc, val) => acc + val, 0);
    const avg = Math.round(sum / count);
    const min = sorted[0];
    const max = sorted[count - 1];

    const percentile = (p: number): number => {
      const idx = Math.ceil((p / 100) * count) - 1;
      return sorted[Math.max(0, Math.min(idx, count - 1))];
    };

    return {
      count,
      min,
      max,
      avg,
      p50: percentile(50),
      p90: percentile(90),
      p95: percentile(95),
      p99: percentile(99),
    };
  }
}
