/**
 * SandboxDriver Interface
 * Invariant 9: The sandbox is behind a SandboxDriver interface.
 * Any development-only driver must be clearly named and documented as NOT a security boundary.
 */

export interface SandboxSpec {
  capsuleId: string;
  versionId: string;
  imageOrArtifactRef: string;
  port: number;
  env?: Record<string, string>;
  memoryLimitMb?: number;
  cpuLimit?: string;
  readOnlyRootfs?: boolean;
}

export interface SandboxInstance {
  id: string;
  capsuleId: string;
  status: 'pending' | 'running' | 'stopped' | 'failed';
  assignedPort: number;
  createdAt: Date;
}

export interface SandboxDriver {
  name: string;
  create(spec: SandboxSpec): Promise<SandboxInstance>;
  start(id: string): Promise<void>;
  stop(id: string): Promise<void>;
  destroy(id: string): Promise<void>;
  inspect(id: string): Promise<SandboxInstance | null>;
}
