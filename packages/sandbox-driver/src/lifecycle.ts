/**
 * CapsuleLifecycleManager
 *
 * Implements the runtime lifecycle per docs/TRD.md:
 * - build/prepare from the bundle
 * - start on demand
 * - suspend when idle
 * - resume on request
 * - recover after crash
 */
import path from 'node:path';
import fs from 'node:fs/promises';
import type {
  SandboxDriver,
  SandboxSpec,
  SandboxInstance,
  SandboxStatus,
  ForwardRequest,
  ForwardResponse,
  SandboxLimits,
} from './interface.js';
import { DockerDevDriver } from './drivers/docker.js';
import { GVisorDriver, type GVisorDriverOptions } from './drivers/gvisor.js';
import { MockSandboxDriver } from './drivers/mock.js';

export interface DriverFactoryOptions {
  driverType?: 'gvisor' | 'docker' | 'mock';
  gvisorOptions?: GVisorDriverOptions;
}

/**
 * Factory creating the appropriate SandboxDriver based on environment and configuration.
 * Automatically selects GVisorDriver in production mode.
 */
export function createDefaultSandboxDriver(options: DriverFactoryOptions = {}): SandboxDriver {
  const driverType =
    options.driverType ||
    process.env.SANDBOX_DRIVER ||
    (process.env.NODE_ENV === 'production' ? 'gvisor' : 'docker');

  if (driverType === 'gvisor') {
    return new GVisorDriver(options.gvisorOptions);
  }

  if (driverType === 'mock') {
    return new MockSandboxDriver();
  }

  // Fall back to DockerDevDriver (which contains the production startup guard)
  return new DockerDevDriver();
}

export interface LifecycleConfig {
  driver: SandboxDriver;
  baseDataDir?: string;
  defaultLimits?: Partial<SandboxLimits>;
  idleTimeoutMs?: number;
}

export class CapsuleLifecycleManager {
  private driver: SandboxDriver;
  private baseDataDir: string;
  private defaultLimits: Partial<SandboxLimits>;
  private idleTimeoutMs: number;
  private instances = new Map<string, SandboxInstance>(); // keyed by appKey

  constructor(config: LifecycleConfig) {
    this.driver = config.driver;
    this.baseDataDir = config.baseDataDir || path.resolve(process.cwd(), 'data', 'capsules');
    this.defaultLimits = config.defaultLimits || {
      cpu: '0.5',
      memoryMb: 256,
      pidsLimit: 64,
      timeoutSeconds: 30,
    };
    this.idleTimeoutMs = config.idleTimeoutMs || 300_000;
  }

  getDriver(): SandboxDriver {
    return this.driver;
  }

  /**
   * Prepare a capsule execution environment from a bundle.
   * Ensures the persistent data directory exists and returns a validated SandboxSpec.
   */
  async prepareCapsule(params: {
    capsuleId: string;
    versionId: string;
    appKey: string;
    orgId?: string;
    bundlePath: string;
    manifest?: Record<string, any>;
    customDataDir?: string;
    limits?: Partial<SandboxLimits>;
    env?: Record<string, string>;
  }): Promise<SandboxSpec> {
    const dataDir = params.customDataDir || path.join(this.baseDataDir, params.capsuleId, 'data');
    await fs.mkdir(dataDir, { recursive: true });
    await fs.mkdir(path.join(dataDir, 'blobs'), { recursive: true });

    // Ensure @capsule/sdk is available and up-to-date in bundle's node_modules
    const sdkTargetDir = path.join(params.bundlePath, 'node_modules', '@capsule', 'sdk');
    const possibleSdkDirs = [
      path.resolve(process.cwd(), 'packages', 'sdk'),
      path.resolve(process.cwd(), 'node_modules', '@capsule', 'sdk'),
    ];
    for (const sdkSourceDir of possibleSdkDirs) {
      try {
        const sourceDist = path.join(sdkSourceDir, 'dist');
        const distFiles = await fs.readdir(sourceDist);
        await fs.mkdir(path.join(sdkTargetDir, 'dist'), { recursive: true });
        await fs.copyFile(path.join(sdkSourceDir, 'package.json'), path.join(sdkTargetDir, 'package.json'));
        for (const file of distFiles) {
          await fs.copyFile(path.join(sourceDist, file), path.join(sdkTargetDir, 'dist', file));
        }
        break;
      } catch {
        // Continue
      }
    }

    // Parse limits from manifest if present, merged with defaults & overrides
    const manifestLimits = params.manifest?.limits;
    const limits: Partial<SandboxLimits> = {
      cpu: params.limits?.cpu || manifestLimits?.cpu || this.defaultLimits.cpu,
      memoryMb: params.limits?.memoryMb || manifestLimits?.memory_mb || this.defaultLimits.memoryMb,
      pidsLimit: params.limits?.pidsLimit || this.defaultLimits.pidsLimit,
      timeoutSeconds:
        params.limits?.timeoutSeconds ||
        manifestLimits?.request_timeout_s ||
        this.defaultLimits.timeoutSeconds,
    };

    // Capability enforcement at sandbox layer:
    // 1. Database capability: only assign dataDir if declared in capabilities
    const hasDb = Boolean(params.manifest?.capabilities?.db);
    const effectiveDataDir = hasDb ? path.resolve(dataDir) : '';

    // 2. Egress capability: default deny network isolation unless declared
    const hasEgress =
      Array.isArray(params.manifest?.egress) && params.manifest.egress.length > 0;
    const egressProxyUrl = process.env.EGRESS_PROXY_URL || 'http://127.0.0.1:19080';

    const env: Record<string, string> = { ...(params.env || {}) };
    if (hasEgress) {
      env.HTTP_PROXY = egressProxyUrl;
      env.HTTPS_PROXY = egressProxyUrl;
      env.ALL_PROXY = egressProxyUrl;
      env.http_proxy = egressProxyUrl;
      env.https_proxy = egressProxyUrl;
    }

    const spec: SandboxSpec = {
      capsuleId: params.capsuleId,
      versionId: params.versionId,
      appKey: params.appKey,
      orgId: params.orgId,
      bundlePath: path.resolve(params.bundlePath),
      dataDir: effectiveDataDir,
      manifest: params.manifest,
      limits,
      env,
      networkMode: hasEgress ? 'bridge' : 'none', // Default deny: no outbound network
      port: 3000,
    };

    return spec;
  }


  /**
   * Start a capsule on demand.
   * If an instance is already running, returns it.
   * If suspended, resumes it.
   * If crashed/failed, recovers it.
   */
  async startOnDemand(spec: SandboxSpec): Promise<SandboxInstance> {
    let instance = this.instances.get(spec.appKey);

    if (instance) {
      const currentStatus = await this.driver.status(instance.id);
      if (currentStatus === 'running') {
        return instance;
      }
      if (currentStatus === 'suspended') {
        await this.driver.resume(instance.id);
        instance.status = 'running';
        instance.lastActiveAt = new Date();
        return instance;
      }
      if (currentStatus === 'crashed' || currentStatus === 'failed') {
        instance = await this.driver.recover(instance.id);
        this.instances.set(spec.appKey, instance);
        return instance;
      }
      // If stopped, clean up old record and start fresh
      await this.driver.destroy(instance.id).catch(() => {});
    }

    instance = await this.driver.start(spec);
    this.instances.set(spec.appKey, instance);
    return instance;
  }

  /**
   * Forward an incoming HTTP request into the capsule.
   * Automatically starts or resumes the sandbox if it is idle/suspended/stopped (Wake-on-Request).
   */
  async handleRequest(spec: SandboxSpec, req: ForwardRequest): Promise<ForwardResponse> {
    const instance = await this.startOnDemand(spec);
    try {
      const response = await this.driver.forwardRequest(instance.id, req);
      instance.lastActiveAt = new Date();
      return response;
    } catch (err: any) {
      // Check if container crashed during execution
      const st = await this.driver.status(instance.id);
      if (st === 'crashed' || st === 'failed') {
        await this.driver.recover(instance.id).catch(() => {});
      }
      throw err;
    }
  }

  /**
   * Suspend all running capsules that have been idle longer than threshold.
   */
  async suspendIdle(customThresholdMs?: number): Promise<string[]> {
    const threshold = customThresholdMs || this.idleTimeoutMs;
    const now = Date.now();
    const suspendedIds: string[] = [];

    for (const [_, instance] of this.instances.entries()) {
      if (instance.status === 'running') {
        const idleTime = now - instance.lastActiveAt.getTime();
        if (idleTime >= threshold) {
          await this.driver.suspend(instance.id);
          instance.status = 'suspended';
          suspendedIds.push(instance.id);
        }
      }
    }

    return suspendedIds;
  }

  /**
   * Suspend a specific capsule by appKey.
   */
  async suspend(appKey: string): Promise<void> {
    const instance = this.instances.get(appKey);
    if (!instance) throw new Error(`No instance tracked for appKey: ${appKey}`);
    await this.driver.suspend(instance.id);
    instance.status = 'suspended';
  }

  /**
   * Resume a specific capsule by appKey.
   */
  async resume(appKey: string): Promise<void> {
    const instance = this.instances.get(appKey);
    if (!instance) throw new Error(`No instance tracked for appKey: ${appKey}`);
    await this.driver.resume(instance.id);
    instance.status = 'running';
    instance.lastActiveAt = new Date();
  }

  /**
   * Suspend all running sandboxes belonging to an organization.
   */
  async suspendOrg(orgId: string): Promise<string[]> {
    const suspendedIds: string[] = [];
    for (const [_, instance] of this.instances.entries()) {
      if (instance.spec.orgId === orgId && instance.status === 'running') {
        await this.driver.suspend(instance.id);
        instance.status = 'suspended';
        suspendedIds.push(instance.id);
      }
    }
    return suspendedIds;
  }

  /**
   * Resume all suspended sandboxes belonging to an organization.
   */
  async resumeOrg(orgId: string): Promise<string[]> {
    const resumedIds: string[] = [];
    for (const [_, instance] of this.instances.entries()) {
      if (instance.spec.orgId === orgId && instance.status === 'suspended') {
        await this.driver.resume(instance.id);
        instance.status = 'running';
        instance.lastActiveAt = new Date();
        resumedIds.push(instance.id);
      }
    }
    return resumedIds;
  }


  /**
   * Recover a capsule if it has crashed.
   */
  async recoverAfterCrash(appKey: string): Promise<SandboxInstance> {
    const instance = this.instances.get(appKey);
    if (!instance) throw new Error(`No instance tracked for appKey: ${appKey}`);
    const recovered = await this.driver.recover(instance.id);
    this.instances.set(appKey, recovered);
    return recovered;
  }

  /**
   * Stop a running capsule.
   */
  async stop(appKey: string): Promise<void> {
    const instance = this.instances.get(appKey);
    if (instance) {
      await this.driver.stop(instance.id);
      instance.status = 'stopped';
    }
  }

  /**
   * Destroy and clean up a capsule instance.
   */
  async destroy(appKey: string): Promise<void> {
    const instance = this.instances.get(appKey);
    if (instance) {
      await this.driver.destroy(instance.id);
      this.instances.delete(appKey);
    }
  }

  /**
   * Query status of an appKey.
   */
  async getStatus(appKey: string): Promise<SandboxStatus> {
    const instance = this.instances.get(appKey);
    if (!instance) return 'stopped';
    return this.driver.status(instance.id);
  }

  getInstance(appKey: string): SandboxInstance | undefined {
    return this.instances.get(appKey);
  }

  listInstances(): SandboxInstance[] {
    return Array.from(this.instances.values());
  }

  /**
   * Export the SQLite database for a capsule to a target path.
   */
  async exportDatabase(capsuleId: string, destinationPath: string): Promise<void> {
    const dataDir = path.join(this.baseDataDir, capsuleId, 'data');
    const dbFile = path.join(dataDir, 'app.sqlite');
    try {
      await fs.access(dbFile);
    } catch {
      throw new Error(`Database file does not exist for capsule ${capsuleId}`);
    }
    const destDir = path.dirname(path.resolve(destinationPath));
    await fs.mkdir(destDir, { recursive: true });
    await fs.copyFile(dbFile, destinationPath);
  }
}
