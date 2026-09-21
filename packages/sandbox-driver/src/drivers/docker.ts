/**
 * DockerDevDriver
 *
 * DEVELOPMENT driver using Docker with the strictest flags available:
 * - non-root user (node / 1000:1000)
 * - read-only root filesystem
 * - dropped all Linux capabilities (--cap-drop=ALL)
 * - no-new-privileges security option
 * - no network by default (--network=none)
 * - CPU, memory, and PID limits
 *
 * WARNING: This driver is for local development and testing only.
 * It is NOT a production security boundary.
 */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import fs from 'node:fs/promises';
import type {
  SandboxDriver,
  SandboxSpec,
  SandboxInstance,
  SandboxStatus,
  LogOptions,
  ForwardRequest,
  ForwardResponse,
} from '../interface.js';

const execFileAsync = promisify(execFile);

export class DockerDevDriver implements SandboxDriver {
  readonly name = 'docker-dev-driver';
  private instances = new Map<string, SandboxInstance>();

  constructor() {
    console.warn(
      '[WARNING] DockerDevDriver is for local development and testing only. It is NOT a security boundary.'
    );
  }

  private normalizePathForDocker(p: string): string {
    return path.resolve(p).replace(/\\/g, '/');
  }

  private parseCpuLimit(cpu?: string): string {
    if (!cpu || cpu === 'small') return '0.5';
    if (cpu === 'medium') return '1.0';
    if (cpu === 'large') return '2.0';
    return cpu;
  }

  async start(spec: SandboxSpec): Promise<SandboxInstance> {
    const instanceId = `capsule-${spec.capsuleId}-${Date.now()}`;
    const cpuLimit = this.parseCpuLimit(spec.limits?.cpu);
    const memoryMb = spec.limits?.memoryMb || 256;
    const pidsLimit = spec.limits?.pidsLimit || 64;
    const networkMode = spec.networkMode || 'none';

    // Ensure data directory exists on host if dataDir is specified
    if (spec.dataDir) {
      await fs.mkdir(spec.dataDir, { recursive: true });
      await fs.mkdir(path.join(spec.dataDir, 'blobs'), { recursive: true });
    }

    const normalizedAppDir = this.normalizePathForDocker(spec.bundlePath);

    const dbMaxSizeMb =
      spec.manifest?.capabilities?.db?.max_size_mb ||
      spec.manifest?.limits?.db_max_mb ||
      50;

    const dockerArgs = [
      'run',
      '-d',
      '--name', instanceId,
      // 1. Non-root user (node user UID 1000 in node:22-alpine)
      '--user', '1000:1000',
      // 2. Read-only root filesystem
      '--read-only',
      // 3. Dropped capabilities & no privilege escalation
      '--cap-drop=ALL',
      '--security-opt', 'no-new-privileges:true',
      // 4. Temporary writable scratch spaces
      '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
      '--tmpfs', '/run:rw,noexec,nosuid,size=16m',
      // 5. Volume mounts (read-only app code)
      '-v', `${normalizedAppDir}:/app:ro`,
    ];

    // Mount writable /data only if dataDir is provided (db capability declared)
    if (spec.dataDir) {
      const normalizedDataDir = this.normalizePathForDocker(spec.dataDir);
      dockerArgs.push('-v', `${normalizedDataDir}:/data:rw`);
    }

    dockerArgs.push(
      // 6. Resource limits
      '--cpus', cpuLimit,
      '--memory', `${memoryMb}m`,
      '--memory-swap', `${memoryMb}m`,
      '--pids-limit', String(pidsLimit),
      // 7. Network isolation
      '--network', networkMode,
      // 8. Working directory and environment
      '-w', '/app',
      '-e', 'NODE_ENV=production',
      '-e', 'PORT=3000',
      '-e', `CAPSULE_ID=${spec.capsuleId}`,
      '-e', `APP_ID=${spec.appKey}`
    );

    if (spec.dataDir) {
      dockerArgs.push(
        '-e', 'DATABASE_PATH=/data/app.sqlite',
        '-e', 'CAPSULE_BLOB_DIR=/data/blobs',
        '-e', `DB_MAX_SIZE_MB=${dbMaxSizeMb}`
      );
    }

    if (process.env.CAPSULE_IDENTITY_SECRET) {
      dockerArgs.push('-e', `CAPSULE_IDENTITY_SECRET=${process.env.CAPSULE_IDENTITY_SECRET}`);
    }

    if (spec.env) {
      for (const [key, value] of Object.entries(spec.env)) {
        dockerArgs.push('-e', `${key}=${value}`);
      }
    }

    if (networkMode === 'bridge' && spec.port) {
      dockerArgs.push('-p', `127.0.0.1:${spec.port}:3000`);
    }

    // Determine entrypoint: check dist/index.js, src/index.js, index.js
    let entrypoint = 'dist/index.js';
    try {
      await fs.access(path.join(spec.bundlePath, 'dist', 'index.js'));
      entrypoint = 'dist/index.js';
    } catch {
      try {
        await fs.access(path.join(spec.bundlePath, 'src', 'index.js'));
        entrypoint = 'src/index.js';
      } catch {
        entrypoint = 'index.js';
      }
    }

    // Base runtime image and command
    dockerArgs.push('node:22-alpine', 'node', entrypoint);

    try {
      await execFileAsync('docker', dockerArgs);

      const now = new Date();
      const instance: SandboxInstance = {
        id: instanceId,
        capsuleId: spec.capsuleId,
        versionId: spec.versionId,
        status: 'running',
        spec,
        assignedPort: spec.port,
        createdAt: now,
        startedAt: now,
        lastActiveAt: now,
      };
      this.instances.set(instanceId, instance);

      // Await container readiness
      await this.waitForReady(instanceId, 15000);

      return instance;
    } catch (err: any) {
      await this.destroy(instanceId).catch(() => {});
      throw new Error(`Failed to start Docker sandbox: ${err.message || err}`);
    }
  }

  private async waitForReady(instanceId: string, timeoutMs: number): Promise<void> {
    const startTime = Date.now();
    while (Date.now() - startTime < timeoutMs) {
      try {
        const resp = await this.forwardRequest(instanceId, {
          method: 'GET',
          path: '/health',
        });
        if (resp.statusCode === 200) {
          return;
        }
      } catch {
        // Retry
      }
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    throw new Error(`Sandbox ${instanceId} failed to become ready within ${timeoutMs}ms.`);
  }

  async stop(instanceId: string): Promise<void> {
    try {
      await execFileAsync('docker', ['stop', '-t', '2', instanceId]);
      const inst = this.instances.get(instanceId);
      if (inst) inst.status = 'stopped';
    } catch (err: any) {
      throw new Error(`Failed to stop sandbox ${instanceId}: ${err.message}`);
    }
  }

  async suspend(instanceId: string): Promise<void> {
    try {
      await execFileAsync('docker', ['pause', instanceId]);
      const inst = this.instances.get(instanceId);
      if (inst) inst.status = 'suspended';
    } catch (err: any) {
      throw new Error(`Failed to suspend sandbox ${instanceId}: ${err.message}`);
    }
  }

  async resume(instanceId: string): Promise<void> {
    try {
      await execFileAsync('docker', ['unpause', instanceId]);
      const inst = this.instances.get(instanceId);
      if (inst) {
        inst.status = 'running';
        inst.lastActiveAt = new Date();
      }
    } catch (err: any) {
      throw new Error(`Failed to resume sandbox ${instanceId}: ${err.message}`);
    }
  }

  async status(instanceId: string): Promise<SandboxStatus> {
    try {
      const { stdout } = await execFileAsync('docker', [
        'inspect',
        '--format',
        '{{json .State}}',
        instanceId,
      ]);
      const state = JSON.parse(stdout.trim());

      let status: SandboxStatus = 'stopped';
      if (state.Paused) {
        status = 'suspended';
      } else if (state.Running) {
        status = 'running';
      } else if (state.OOMKilled || (state.ExitCode !== 0 && state.ExitCode !== 143 && state.ExitCode !== 137)) {
        status = 'crashed';
      } else {
        status = 'stopped';
      }

      const inst = this.instances.get(instanceId);
      if (inst) inst.status = status;
      return status;
    } catch {
      return 'stopped';
    }
  }

  async logs(instanceId: string, options?: LogOptions): Promise<string[]> {
    const args = ['logs'];
    if (options?.tail) {
      args.push('--tail', String(options.tail));
    }
    args.push(instanceId);

    try {
      const { stdout, stderr } = await execFileAsync('docker', args);
      const output = (stdout + '\n' + stderr).trim();
      return output ? output.split('\n') : [];
    } catch (err: any) {
      throw new Error(`Failed to read logs for ${instanceId}: ${err.message}`);
    }
  }

  async forwardRequest(instanceId: string, req: ForwardRequest): Promise<ForwardResponse> {
    const inst = this.instances.get(instanceId);
    if (!inst) throw new Error(`Sandbox ${instanceId} is not tracked by driver.`);

    inst.lastActiveAt = new Date();

    // Prepare JSON payload for the bridge script
    const payload = JSON.stringify({
      method: req.method,
      path: req.path,
      headers: req.headers || {},
      body: req.body || '',
    });

    const bridgeScript =
      "const http=require('http');const reqData=JSON.parse(process.argv[1]);const options={hostname:'127.0.0.1',port:3000,path:reqData.path,method:reqData.method,headers:reqData.headers};const clientReq=http.request(options,(res)=>{let body='';res.on('data',d=>body+=d);res.on('end',()=>{console.log(JSON.stringify({statusCode:res.statusCode,headers:res.headers,body}));});});clientReq.on('error',(e)=>{console.error('BRIDGE_ERROR:'+e.message);process.exit(1);});if(reqData.body)clientReq.write(reqData.body);clientReq.end();";

    try {
      const { stdout } = await execFileAsync('docker', [
        'exec',
        '-i',
        instanceId,
        'node',
        '-e',
        bridgeScript,
        payload,
      ]);

      const lines = stdout.trim().split('\n');
      const jsonLine = lines.find((l) => l.trim().startsWith('{') && l.trim().endsWith('}')) || stdout.trim();
      const result = JSON.parse(jsonLine);
      return {
        statusCode: result.statusCode,
        headers: result.headers,
        body: result.body,
      };
    } catch (err: any) {
      throw new Error(`Failed to forward request to sandbox ${instanceId}: ${err.message || err}`);
    }
  }

  async recover(instanceId: string): Promise<SandboxInstance> {
    const inst = this.instances.get(instanceId);
    if (!inst) throw new Error(`Sandbox ${instanceId} not found.`);

    await this.destroy(instanceId).catch(() => {});
    return this.start(inst.spec);
  }

  async destroy(instanceId: string): Promise<void> {
    try {
      await execFileAsync('docker', ['rm', '-f', instanceId]);
    } catch {
      // Ignore if container is already gone
    }
    this.instances.delete(instanceId);
  }

  /**
   * Export the SQLite database for an instance or data directory to a destination path.
   */
  async exportDatabase(instanceIdOrDataDir: string, destinationPath: string): Promise<void> {
    let dbFile: string;
    const instance = this.instances.get(instanceIdOrDataDir);
    if (instance) {
      dbFile = path.join(instance.spec.dataDir, 'app.sqlite');
    } else {
      dbFile = path.join(instanceIdOrDataDir, 'app.sqlite');
    }

    try {
      await fs.access(dbFile);
    } catch {
      throw new Error(`Database file does not exist: ${dbFile}`);
    }

    const destDir = path.dirname(path.resolve(destinationPath));
    await fs.mkdir(destDir, { recursive: true });
    await fs.copyFile(dbFile, destinationPath);
  }
}
