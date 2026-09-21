import { describe, it, expect } from 'vitest';
import { DevMockSandboxDriver } from '../src/index.js';

describe('SandboxDriver Package', () => {
  it('should instantiate DevMockSandboxDriver with explicit mock name', () => {
    const driver = new DevMockSandboxDriver();
    expect(driver.name).toBe('dev-mock-driver');
  });

  it('should create and manage mock sandbox lifecycle', async () => {
    const driver = new DevMockSandboxDriver();
    const sandbox = await driver.create({
      capsuleId: 'test-capsule',
      versionId: 'v1',
      imageOrArtifactRef: 'test-ref',
      port: 8081,
    });

    expect(sandbox.id).toBe('mock-test-capsule');
    expect(sandbox.status).toBe('pending');

    await driver.start(sandbox.id);
    const inspected = await driver.inspect(sandbox.id);
    expect(inspected?.status).toBe('running');

    await driver.stop(sandbox.id);
    const stopped = await driver.inspect(sandbox.id);
    expect(stopped?.status).toBe('stopped');

    await driver.destroy(sandbox.id);
    const destroyed = await driver.inspect(sandbox.id);
    expect(destroyed).toBeNull();
  });
});
