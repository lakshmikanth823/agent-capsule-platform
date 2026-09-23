/**
 * SandboxDriver Interface
 * Invariant 9: The sandbox is behind a SandboxDriver interface.
 * Any development-only driver must be clearly named and documented as NOT a security boundary.
 */

export type SandboxStatus =
  "pending" | "running" | "suspended" | "stopped" | "failed" | "crashed";

export interface SandboxLimits {
  cpu: string; // e.g. "0.5" or "small"
  memoryMb: number; // e.g. 256
  pidsLimit: number; // e.g. 64
  timeoutSeconds: number; // e.g. 30
}

export interface SandboxSpec {
  capsuleId: string;
  versionId: string;
  appKey: string;
  orgId?: string;
  callerOrgId?: string;
  bundlePath: string; // path to application bundle (tar.gz or extracted dir)
  dataDir: string; // persistent per-capsule directory for SQLite
  manifest?: Record<string, any>;
  limits?: Partial<SandboxLimits>;
  env?: Record<string, string>;
  networkMode?: "none" | "bridge"; // 'none' is the secure default
  port?: number; // internal application port (default 3000)
}

export interface ColdStartStats {
  count: number;
  min: number;
  max: number;
  avg: number;
  p50: number;
  p90: number;
  p95: number;
  p99: number;
}

export interface SandboxInstance {
  id: string; // container or VM identifier
  capsuleId: string;
  versionId: string;
  status: SandboxStatus;
  spec: SandboxSpec;
  assignedPort?: number;
  createdAt: Date;
  startedAt?: Date;
  lastActiveAt: Date;
  coldStartMs?: number; // Measured time to become ready (ms)
}

export interface ForwardRequest {
  method: string;
  path: string;
  headers?: Record<string, string>;
  body?: string | Buffer;
}

export interface ForwardResponse {
  statusCode: number;
  headers: Record<string, string>;
  body: string;
}

export interface LogOptions {
  tail?: number;
  since?: Date;
}

export interface SandboxDriver {
  readonly name: string;

  /** Start a sandbox instance for the specified capsule version */
  start(spec: SandboxSpec): Promise<SandboxInstance>;

  /** Stop a running sandbox instance */
  stop(instanceId: string): Promise<void>;

  /** Suspend a running sandbox instance when idle (e.g. freeze/pause) */
  suspend(instanceId: string): Promise<void>;

  /** Resume a suspended sandbox instance on incoming traffic */
  resume(instanceId: string): Promise<void>;

  /** Query current sandbox execution status */
  status(instanceId: string): Promise<SandboxStatus>;

  /** Retrieve stdout/stderr logs from the sandbox */
  logs(instanceId: string, options?: LogOptions): Promise<string[]>;

  /** Forward an incoming HTTP request into the capsule */
  forwardRequest(
    instanceId: string,
    req: ForwardRequest,
  ): Promise<ForwardResponse>;

  /** Recover a crashed or dead instance */
  recover(instanceId: string): Promise<SandboxInstance>;

  /** Destroy and clean up all sandbox resources */
  destroy(instanceId: string): Promise<void>;
}
