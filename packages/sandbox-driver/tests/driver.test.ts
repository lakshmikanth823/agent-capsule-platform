import { describe, it, expect } from 'vitest';
import path from 'node:path';
import fs from 'node:fs/promises';
import {
  DevMockSandboxDriver,
  GVisorDriver,
  FirecrackerDriver,
  ManagedSandboxDriver,
  NotImplementedError,
  CapsuleLifecycleManager,
  type SandboxSpec,
} from '../src/index.js';

describe('DevMockSandboxDriver', () => {
  const sampleSpec: SandboxSpec = {
    capsuleId: 'app-test-1',
    versionId: 'v1.0.0',
    appKey: 'app-test-1',
    bundlePath: path.resolve('examples/leave-tracker'),
    dataDir: path.resolve('data/test-mock/data'),
    networkMode: 'none',
    port: 3000,
  };

  it('should instantiate with explicit mock name', () => {
    const driver = new DevMockSandboxDriver();
    expect(driver.name).toBe('dev-mock-driver');
  });

  it('should start, forward requests, and stop', async () => {
    const driver = new DevMockSandboxDriver();
    const instance = await driver.start(sampleSpec);

    expect(instance.status).toBe('running');
    expect(instance.capsuleId).toBe('app-test-1');

    // Health check request
    const healthResp = await driver.forwardRequest(instance.id, {
      method: 'GET',
      path: '/health',
    });
    expect(healthResp.statusCode).toBe(200);
    const healthBody = JSON.parse(healthResp.body);
    expect(healthBody.status).toBe('healthy');

    // Custom mock response
    driver.setMockResponse('/api/identity', () => ({
      statusCode: 200,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ authenticated: true, sub: 'user_mock' }),
    }));

    const idResp = await driver.forwardRequest(instance.id, {
      method: 'GET',
      path: '/api/identity',
    });
    expect(idResp.statusCode).toBe(200);
    expect(JSON.parse(idResp.body).sub).toBe('user_mock');

    // Suspend and resume
    await driver.suspend(instance.id);
    expect(await driver.status(instance.id)).toBe('suspended');

    await expect(
      driver.forwardRequest(instance.id, { method: 'GET', path: '/health' })
    ).rejects.toThrow('Cannot forward request: instance');

    await driver.resume(instance.id);
    expect(await driver.status(instance.id)).toBe('running');

    // Logs
    const logs = await driver.logs(instance.id);
    expect(logs.length).toBeGreaterThan(0);

    // Stop and destroy
    await driver.stop(instance.id);
    expect(await driver.status(instance.id)).toBe('stopped');

    await driver.destroy(instance.id);
  });
});

describe('Production Driver Stubs', () => {
  const sampleSpec: SandboxSpec = {
    capsuleId: 'app-prod-1',
    versionId: 'v1.0.0',
    appKey: 'app-prod-1',
    bundlePath: '/tmp/bundle',
    dataDir: '/tmp/data',
  };

  it('GVisorDriver should throw NotImplementedError', async () => {
    const driver = new GVisorDriver();
    expect(driver.name).toBe('gvisor');
    await expect(driver.start(sampleSpec)).rejects.toThrow(NotImplementedError);
  });

  it('FirecrackerDriver should throw NotImplementedError', async () => {
    const driver = new FirecrackerDriver();
    expect(driver.name).toBe('firecracker');
    await expect(driver.start(sampleSpec)).rejects.toThrow(NotImplementedError);
  });

  it('ManagedSandboxDriver should throw NotImplementedError', async () => {
    const driver = new ManagedSandboxDriver();
    expect(driver.name).toBe('managed-provider');
    await expect(driver.start(sampleSpec)).rejects.toThrow(NotImplementedError);
  });
});

describe('CapsuleLifecycleManager', () => {
  const testBaseDataDir = path.resolve('data/test-lifecycle');

  it('should prepare capsule spec and configure limits from manifest', async () => {
    const driver = new DevMockSandboxDriver();
    const manager = new CapsuleLifecycleManager({
      driver,
      baseDataDir: testBaseDataDir,
    });

    const spec = await manager.prepareCapsule({
      capsuleId: 'leave-tracker',
      versionId: 'v1',
      appKey: 'leave-tracker',
      bundlePath: path.resolve('examples/leave-tracker'),
      manifest: {
        limits: {
          cpu: 'small',
          memory_mb: 256,
          request_timeout_s: 30,
        },
      },
    });

    expect(spec.capsuleId).toBe('leave-tracker');
    expect(spec.limits?.cpu).toBe('small');
    expect(spec.limits?.memoryMb).toBe(256);
    expect(spec.limits?.timeoutSeconds).toBe(30);
    expect(spec.networkMode).toBe('none');

    // Clean up created data directory
    await fs.rm(testBaseDataDir, { recursive: true, force: true }).catch(() => {});
  });

  it('should handle request with wake-on-request and idle suspend', async () => {
    const driver = new DevMockSandboxDriver();
    const manager = new CapsuleLifecycleManager({
      driver,
      baseDataDir: testBaseDataDir,
      idleTimeoutMs: 50, // 50ms for fast test
    });

    const spec = await manager.prepareCapsule({
      capsuleId: 'calc-app',
      versionId: 'v1',
      appKey: 'calc-app',
      bundlePath: path.resolve('examples/leave-tracker'),
    });

    // 1. Send request (wakes/starts container automatically)
    const resp = await manager.handleRequest(spec, {
      method: 'GET',
      path: '/health',
    });
    expect(resp.statusCode).toBe(200);

    const instance = manager.getInstance('calc-app');
    expect(instance?.status).toBe('running');

    // 2. Wait for idle timeout
    await new Promise((resolve) => setTimeout(resolve, 60));

    // 3. Suspend idle instances
    const suspended = await manager.suspendIdle();
    expect(suspended).toContain(instance?.id);
    expect(instance?.status).toBe('suspended');

    // 4. Send another request (automatically wakes/resumes)
    const resp2 = await manager.handleRequest(spec, {
      method: 'GET',
      path: '/health',
    });
    expect(resp2.statusCode).toBe(200);
    expect(instance?.status).toBe('running');

    // Clean up
    await manager.destroy('calc-app');
    await fs.rm(testBaseDataDir, { recursive: true, force: true }).catch(() => {});
  });
});
