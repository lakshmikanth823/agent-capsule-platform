import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import path from 'node:path';
import fs from 'node:fs/promises';
import {
  DockerDevDriver,
  GVisorDriver,
  isDockerAvailable,
  type SandboxDriver,
  type SandboxSpec,
} from '../src/index.js';

const hasDocker = isDockerAvailable();

describe('SandboxDriver Conformance Test Suite (Prompt 21B)', () => {
  const driversToTest: Array<{
    name: string;
    factory: () => SandboxDriver;
    buildArgs: (driver: SandboxDriver, spec: SandboxSpec, id: string) => Promise<string[]>;
  }> = [
    {
      name: 'DockerDevDriver',
      factory: () => new DockerDevDriver(),
      buildArgs: async (driver: any, spec: SandboxSpec, id: string) =>
        driver.buildExecutionArgs(spec, id),
    },
    {
      name: 'GVisorDriver',
      factory: () => new GVisorDriver(),
      buildArgs: async (driver: any, spec: SandboxSpec, id: string) =>
        driver.buildExecutionArgs(spec, id),
    },
  ];

  const testBaseDir = path.resolve('data/test-conformance');
  const sampleSpec: SandboxSpec = {
    capsuleId: 'conformance-app',
    versionId: 'v1.0.0',
    appKey: 'conformance-app',
    bundlePath: path.resolve('examples/leave-tracker'),
    dataDir: path.join(testBaseDir, 'data'),
    limits: {
      cpu: '0.5',
      memoryMb: 256,
      pidsLimit: 64,
      timeoutSeconds: 30,
    },
    networkMode: 'none',
  };

  beforeAll(async () => {
    await fs.mkdir(testBaseDir, { recursive: true });
    process.env.ALLOW_DEV_FALLBACK = '1';
  });

  afterAll(async () => {
    delete process.env.ALLOW_DEV_FALLBACK;
    await fs.rm(testBaseDir, { recursive: true, force: true }).catch(() => {});
  });

  // -------------------------------------------------------------------------
  // 1. Interface Conformance (Checked against both drivers)
  // -------------------------------------------------------------------------
  for (const { name, factory } of driversToTest) {
    describe(`Interface Conformance: ${name}`, () => {
      it(`should implement all required SandboxDriver methods and properties`, () => {
        const driver = factory();
        expect(typeof driver.name).toBe('string');
        expect(driver.name.length).toBeGreaterThan(0);

        expect(typeof driver.start).toBe('function');
        expect(typeof driver.stop).toBe('function');
        expect(typeof driver.suspend).toBe('function');
        expect(typeof driver.resume).toBe('function');
        expect(typeof driver.status).toBe('function');
        expect(typeof driver.logs).toBe('function');
        expect(typeof driver.forwardRequest).toBe('function');
        expect(typeof driver.recover).toBe('function');
        expect(typeof driver.destroy).toBe('function');
      });

      it(`should return 'stopped' for an unknown instanceId on status()`, async () => {
        const driver = factory();
        const status = await driver.status('non-existent-instance-99999');
        expect(status).toBe('stopped');
      });

      it(`should throw an error on forwardRequest for an un-tracked instance`, async () => {
        const driver = factory();
        await expect(
          driver.forwardRequest('non-existent-instance-99999', {
            method: 'GET',
            path: '/health',
          })
        ).rejects.toThrow();
      });

      it(`should throw an error on recover for an unknown instance`, async () => {
        const driver = factory();
        await expect(driver.recover('non-existent-instance-99999')).rejects.toThrow();
      });

      it(`should safely tolerate destroy on non-existent instance without throwing`, async () => {
        const driver = factory();
        await expect(driver.destroy('non-existent-instance-99999')).resolves.not.toThrow();
      });
    });
  }

  // -------------------------------------------------------------------------
  // 2. Hardened Security Flags Conformance (Checked against both drivers)
  // -------------------------------------------------------------------------
  for (const { name, factory, buildArgs } of driversToTest) {
    describe(`Security Flags Conformance: ${name}`, () => {
      it(`should mandate non-root user (1000:1000)`, async () => {
        const driver = factory();
        const args = await buildArgs(driver, sampleSpec, 'test-sec-user');
        const userIdx = args.indexOf('--user');
        expect(userIdx).not.toBe(-1);
        expect(args[userIdx + 1]).toBe('1000:1000');
      });

      it(`should mandate read-only root filesystem (--read-only)`, async () => {
        const driver = factory();
        const args = await buildArgs(driver, sampleSpec, 'test-sec-ro');
        expect(args).toContain('--read-only');
      });

      it(`should drop all Linux capabilities (--cap-drop=ALL)`, async () => {
        const driver = factory();
        const args = await buildArgs(driver, sampleSpec, 'test-sec-cap');
        expect(args).toContain('--cap-drop=ALL');
      });

      it(`should enforce no-new-privileges security option`, async () => {
        const driver = factory();
        const args = await buildArgs(driver, sampleSpec, 'test-sec-priv');
        expect(args).toContain('no-new-privileges:true');
      });

      it(`should enforce default-deny network mode (--network none)`, async () => {
        const driver = factory();
        const args = await buildArgs(driver, sampleSpec, 'test-sec-net');
        expect(args).toContain('--network');
        expect(args).toContain('none');
      });

      it(`should configure strict resource limits (cpu, memory, pids-limit)`, async () => {
        const driver = factory();
        const args = await buildArgs(driver, sampleSpec, 'test-sec-res');
        expect(args).toContain('--cpus');
        expect(args).toContain('0.5');
        expect(args).toContain('--memory');
        expect(args).toContain('256m');
        expect(args).toContain('--pids-limit');
        expect(args).toContain('64');
      });

      it(`should mount bundle read-only (/app:ro)`, async () => {
        const driver = factory();
        const args = await buildArgs(driver, sampleSpec, 'test-sec-mount');
        const hasAppRo = args.some((arg) => arg.includes('/app:ro'));
        expect(hasAppRo).toBe(true);
      });
    });
  }

  // -------------------------------------------------------------------------
  // 3. Lifecycle Transitions Conformance (Execute start, forward, suspend, resume, stop, destroy)
  // -------------------------------------------------------------------------
  for (const { name, factory } of driversToTest) {
    describe.skipIf(!hasDocker)(`Runtime Lifecycle Conformance: ${name}`, { timeout: 30000 }, () => {
      let driver: SandboxDriver;
      let instanceId: string | null = null;

      afterAll(async () => {
        if (instanceId && driver) {
          await driver.destroy(instanceId).catch(() => {});
        }
      });

      it(`should successfully start a sandbox instance and verify status is 'running'`, async () => {
        driver = factory();
        const spec: SandboxSpec = {
          ...sampleSpec,
          capsuleId: `cf-${name.toLowerCase()}`,
          appKey: `cf-${name.toLowerCase()}`,
          dataDir: path.join(testBaseDir, `data-${name.toLowerCase()}`),
        };

        const instance = await driver.start(spec);
        instanceId = instance.id;

        expect(instance.id).toBeDefined();
        expect(instance.status).toBe('running');
        expect(await driver.status(instance.id)).toBe('running');
      });

      it(`should forward HTTP health check and receive status 200`, async () => {
        if (!instanceId) return;

        const response = await driver.forwardRequest(instanceId, {
          method: 'GET',
          path: '/health',
        });

        expect(response.statusCode).toBe(200);
        const parsed = JSON.parse(response.body);
        expect(parsed.status).toBe('healthy');
      });

      it(`should suspend a running instance into 'suspended' status`, async () => {
        if (!instanceId) return;

        await driver.suspend(instanceId);
        const status = await driver.status(instanceId);
        expect(status).toBe('suspended');
      });

      it(`should resume a suspended instance back to 'running' status`, async () => {
        if (!instanceId) return;

        await driver.resume(instanceId);
        const status = await driver.status(instanceId);
        expect(status).toBe('running');

        // And verify it still responds
        const response = await driver.forwardRequest(instanceId, {
          method: 'GET',
          path: '/health',
        });
        expect(response.statusCode).toBe(200);
      });

      it(`should retrieve log entries via logs()`, async () => {
        if (!instanceId) return;

        const logs = await driver.logs(instanceId, { tail: 20 });
        expect(Array.isArray(logs)).toBe(true);
      });

      it(`should stop the instance cleanly`, async () => {
        if (!instanceId) return;

        await driver.stop(instanceId);
        const status = await driver.status(instanceId);
        expect(status).toBe('stopped');
      });

      it(`should destroy and clean up the container`, async () => {
        if (!instanceId) return;

        await driver.destroy(instanceId);
        const status = await driver.status(instanceId);
        expect(status).toBe('stopped');
        instanceId = null;
      });
    });
  }

  // -------------------------------------------------------------------------
  // 4. Cold Start & Percentiles Verification
  // -------------------------------------------------------------------------
  describe('Cold Start Instrumentation & p95 Reporting', () => {
    it('should compute accurate cold start percentiles (p50, p90, p95, p99)', () => {
      const gv = new GVisorDriver();

      // Seed 100 samples simulating distribution from 400ms to 900ms
      for (let i = 1; i <= 100; i++) {
        gv.recordColdStart(400 + i * 5); // 405ms to 900ms
      }

      const stats = gv.getColdStartStats();
      expect(stats.count).toBe(100);
      expect(stats.min).toBe(405);
      expect(stats.max).toBe(900);
      expect(stats.p50).toBe(650);
      expect(stats.p90).toBe(850);
      expect(stats.p95).toBe(875);
      expect(stats.p99).toBe(895);
      expect(stats.avg).toBe(653);
    });

    it('should report zeroed stats when no samples are recorded', () => {
      const gv = new GVisorDriver();
      const stats = gv.getColdStartStats();
      expect(stats.count).toBe(0);
      expect(stats.p95).toBe(0);
    });
  });

  // -------------------------------------------------------------------------
  // 5. Production Startup Guard Conformance
  // -------------------------------------------------------------------------
  describe('Production Startup Guard Conformance', () => {
    const prevNodeEnv = process.env.NODE_ENV;
    const prevAllowInsecure = process.env.ALLOW_INSECURE_DEV_DRIVER;

    afterAll(() => {
      if (prevNodeEnv !== undefined) {
        process.env.NODE_ENV = prevNodeEnv;
      } else {
        delete process.env.NODE_ENV;
      }
      if (prevAllowInsecure !== undefined) {
        process.env.ALLOW_INSECURE_DEV_DRIVER = prevAllowInsecure;
      } else {
        delete process.env.ALLOW_INSECURE_DEV_DRIVER;
      }
    });

    it('should refuse to start DockerDevDriver in production mode without override', () => {
      const origNodeEnv = process.env.NODE_ENV;
      const origInsecure = process.env.ALLOW_INSECURE_DEV_DRIVER;
      try {
        process.env.NODE_ENV = 'production';
        delete process.env.ALLOW_INSECURE_DEV_DRIVER;

        expect(() => new DockerDevDriver()).toThrow(
          /\[SECURITY INVARIANT VIOLATION\] DockerDevDriver is an insecure development driver and cannot be used in production/
        );
      } finally {
        if (origNodeEnv !== undefined) process.env.NODE_ENV = origNodeEnv;
        else delete process.env.NODE_ENV;
        if (origInsecure !== undefined) process.env.ALLOW_INSECURE_DEV_DRIVER = origInsecure;
        else delete process.env.ALLOW_INSECURE_DEV_DRIVER;
      }
    });

    it('should permit DockerDevDriver in production if ALLOW_INSECURE_DEV_DRIVER=true is set', () => {
      const origNodeEnv = process.env.NODE_ENV;
      const origInsecure = process.env.ALLOW_INSECURE_DEV_DRIVER;
      try {
        process.env.NODE_ENV = 'production';
        process.env.ALLOW_INSECURE_DEV_DRIVER = 'true';

        expect(() => new DockerDevDriver()).not.toThrow();
      } finally {
        if (origNodeEnv !== undefined) process.env.NODE_ENV = origNodeEnv;
        else delete process.env.NODE_ENV;
        if (origInsecure !== undefined) process.env.ALLOW_INSECURE_DEV_DRIVER = origInsecure;
        else delete process.env.ALLOW_INSECURE_DEV_DRIVER;
      }
    });

    it('should permit GVisorDriver in production mode without requiring any override', () => {
      const origNodeEnv = process.env.NODE_ENV;
      const origInsecure = process.env.ALLOW_INSECURE_DEV_DRIVER;
      try {
        process.env.NODE_ENV = 'production';
        delete process.env.ALLOW_INSECURE_DEV_DRIVER;

        expect(() => new GVisorDriver()).not.toThrow();
      } finally {
        if (origNodeEnv !== undefined) process.env.NODE_ENV = origNodeEnv;
        else delete process.env.NODE_ENV;
        if (origInsecure !== undefined) process.env.ALLOW_INSECURE_DEV_DRIVER = origInsecure;
        else delete process.env.ALLOW_INSECURE_DEV_DRIVER;
      }
    });
  });
});
