import { describe, it, expect, afterAll } from 'vitest';
import path from 'node:path';
import fs from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { DockerDevDriver, type SandboxSpec } from '../src/index.js';

const execFileAsync = promisify(execFile);

describe('DockerDevDriver Integration Tests', () => {
  const driver = new DockerDevDriver();
  const testDataDir = path.resolve('data/test-docker-capsule');
  let activeInstanceId: string | null = null;

  const sampleSpec: SandboxSpec = {
    capsuleId: 'leave-tracker-test',
    versionId: 'v1.0.0',
    appKey: 'leave-tracker-test',
    bundlePath: path.resolve('examples/leave-tracker'),
    dataDir: path.join(testDataDir, 'data'),
    limits: {
      cpu: '0.5',
      memoryMb: 128,
      pidsLimit: 32,
      timeoutSeconds: 30,
    },
    networkMode: 'none',
  };

  afterAll(async () => {
    if (activeInstanceId) {
      await driver.destroy(activeInstanceId).catch(() => {});
    }
    await fs.rm(testDataDir, { recursive: true, force: true }).catch(() => {});
  });

  it('should start sample app and forward HTTP requests (Acceptance Criterion)', async () => {
    // Start container with strict flags
    const instance = await driver.start(sampleSpec);
    activeInstanceId = instance.id;

    expect(instance.id).toBeDefined();
    expect(await driver.status(instance.id)).toBe('running');

    // 1. Health check forwardRequest
    const healthResp = await driver.forwardRequest(instance.id, {
      method: 'GET',
      path: '/health',
    });
    expect(healthResp.statusCode).toBe(200);
    const healthData = JSON.parse(healthResp.body);
    expect(healthData.status).toBe('healthy');
    expect(healthData.app).toBe('leave-tracker');

    // 2. Identity inspection route
    const identityPayload = {
      iss: 'platform',
      aud: 'capsule:leave-tracker',
      sub: 'usr_alice_123',
      org_id: 'org_acme',
      groups: ['engineering'],
      roles: ['employee'],
      iat: Math.floor(Date.now() / 1000),
      exp: Math.floor(Date.now() / 1000) + 3600,
    };

    const idResp = await driver.forwardRequest(instance.id, {
      method: 'GET',
      path: '/api/identity',
      headers: {
        'x-capsule-identity': JSON.stringify(identityPayload),
      },
    });
    expect(idResp.statusCode).toBe(200);
    const idData = JSON.parse(idResp.body);
    expect(idData.authenticated).toBe(true);
    expect(idData.identity.sub).toBe('usr_alice_123');
    expect(idData.identity.roles).toContain('employee');

    // 3. Database operation (SQLite POST & GET)
    const createLeaveResp = await driver.forwardRequest(instance.id, {
      method: 'POST',
      path: '/api/leaves',
      headers: {
        'content-type': 'application/json',
        'x-capsule-identity': JSON.stringify(identityPayload),
      },
      body: JSON.stringify({
        start_date: '2026-10-01',
        end_date: '2026-10-05',
        reason: 'Annual Vacation',
      }),
    });
    expect(createLeaveResp.statusCode).toBe(201);
    const created = JSON.parse(createLeaveResp.body);
    expect(created.id).toBe(1);
    expect(created.user_id).toBe('usr_alice_123');
    expect(created.reason).toBe('Annual Vacation');

    // Retrieve leaves
    const listLeavesResp = await driver.forwardRequest(instance.id, {
      method: 'GET',
      path: '/api/leaves',
    });
    expect(listLeavesResp.statusCode).toBe(200);
    const listData = JSON.parse(listLeavesResp.body);
    expect(listData.leaves.length).toBeGreaterThanOrEqual(1);
    expect(listData.leaves[0].reason).toBe('Annual Vacation');
  }, 30000);

  it('should enforce resource limits and security isolation flags in Docker', async () => {
    expect(activeInstanceId).not.toBeNull();

    const { stdout } = await execFileAsync('docker', [
      'inspect',
      '--format',
      '{{json .HostConfig}}',
      activeInstanceId!,
    ]);
    const hostConfig = JSON.parse(stdout.trim());

    // 1. Non-root user (1000:1000)
    const { stdout: userOut } = await execFileAsync('docker', [
      'inspect',
      '--format',
      '{{.Config.User}}',
      activeInstanceId!,
    ]);
    expect(userOut.trim()).toBe('1000:1000');

    // 2. Read-only root filesystem
    expect(hostConfig.ReadonlyRootfs).toBe(true);

    // 3. Dropped all capabilities
    expect(hostConfig.CapDrop).toContain('ALL');

    // 4. No new privileges
    expect(hostConfig.SecurityOpt).toContain('no-new-privileges:true');

    // 5. CPU limit (0.5 cpus = 500,000,000 NanoCPUs)
    expect(hostConfig.NanoCpus).toBe(500000000);

    // 6. Memory limit (128 MB = 134,217,728 bytes)
    expect(hostConfig.Memory).toBe(128 * 1024 * 1024);

    // 7. PID limit
    expect(hostConfig.PidsLimit).toBe(32);

    // 8. Network isolation (default deny)
    expect(hostConfig.NetworkMode).toBe('none');
  });

  it('should prove outbound network access fails by default (Security Invariant 4)', async () => {
    expect(activeInstanceId).not.toBeNull();

    // Probe outbound network inside container
    // Attempting to connect to an external IP (e.g. 1.1.1.1) in --network=none fails immediately
    const probeScript = `
      const http = require('http');
      const req = http.get('http://1.1.1.1', (res) => {
        console.log('UNEXPECTED_SUCCESS');
        process.exit(0);
      });
      req.on('error', (err) => {
        console.log('NETWORK_DENIED:' + err.code);
        process.exit(1);
      });
      req.setTimeout(1000, () => {
        req.destroy();
        console.log('NETWORK_TIMEOUT');
        process.exit(1);
      });
    `;

    let failed = false;
    let errorOutput = '';
    try {
      await execFileAsync('docker', [
        'exec',
        '-i',
        activeInstanceId!,
        'node',
        '-e',
        probeScript,
      ]);
    } catch (err: any) {
      failed = true;
      errorOutput = (err.stdout || '') + (err.stderr || '');
    }

    // In --network=none, outbound network attempt MUST fail
    expect(failed).toBe(true);
    expect(errorOutput).toMatch(/NETWORK_DENIED|ENETUNREACH|EHOSTUNREACH|ENOTFOUND/);
  });

  it('should support suspend, resume, and stop operations', async () => {
    expect(activeInstanceId).not.toBeNull();

    // Suspend
    await driver.suspend(activeInstanceId!);
    expect(await driver.status(activeInstanceId!)).toBe('suspended');

    // Resume
    await driver.resume(activeInstanceId!);
    expect(await driver.status(activeInstanceId!)).toBe('running');

    // Health check still works after resume
    const resp = await driver.forwardRequest(activeInstanceId!, {
      method: 'GET',
      path: '/health',
    });
    expect(resp.statusCode).toBe(200);

    // Stop
    await driver.stop(activeInstanceId!);
    expect(await driver.status(activeInstanceId!)).toBe('stopped');
  });

  it('should recover after crash', async () => {
    // Restart container
    const instance = await driver.start(sampleSpec);
    activeInstanceId = instance.id;

    expect(await driver.status(instance.id)).toBe('running');

    // Kill container to simulate crash
    await execFileAsync('docker', ['kill', instance.id]);

    const statusAfterKill = await driver.status(instance.id);
    expect(['stopped', 'crashed']).toContain(statusAfterKill);

    // Recover instance
    const recovered = await driver.recover(instance.id);
    activeInstanceId = recovered.id;

    expect(await driver.status(recovered.id)).toBe('running');

    const healthResp = await driver.forwardRequest(recovered.id, {
      method: 'GET',
      path: '/health',
    });
    expect(healthResp.statusCode).toBe(200);

    // Clean up
    await driver.destroy(recovered.id);
    activeInstanceId = null;
  }, 30000);
});
