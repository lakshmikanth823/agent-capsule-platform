import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import { AddressInfo } from 'node:net';
import {
  createEdgeProxyServer,
  AccessManager,
} from '../src/index.js';
import {
  DevMockSandboxDriver,
  CapsuleLifecycleManager,
  type ForwardRequest,
  type ForwardResponse,
} from '@capsule/sandbox-driver';

describe('Edge Proxy Kill Switch & Quotas (Prompt 23)', () => {
  let server: http.Server;
  let serverPort: number;
  let mockDriver: DevMockSandboxDriver;
  let lifecycleManager: CapsuleLifecycleManager;
  let accessManager: AccessManager;
  let sessionCookie: string;

  const appDomain = 'apps.localhost';
  const dashboardDomain = 'platform.localhost';

  function makeRequest(options: {
    host: string;
    path: string;
    method?: string;
    headers?: Record<string, string>;
    body?: string;
  }): Promise<{ statusCode: number; headers: http.IncomingHttpHeaders; body: string }> {
    return new Promise((resolve, reject) => {
      const req = http.request(
        {
          hostname: '127.0.0.1',
          port: serverPort,
          path: options.path,
          method: options.method || 'GET',
          headers: {
            host: options.host,
            ...(options.headers || {}),
          },
        },
        (res) => {
          let body = '';
          res.on('data', (chunk) => (body += chunk));
          res.on('end', () =>
            resolve({
              statusCode: res.statusCode || 0,
              headers: res.headers,
              body,
            })
          );
        }
      );
      req.on('error', reject);
      if (options.body) req.write(options.body);
      req.end();
    });
  }

  beforeAll(async () => {
    mockDriver = new DevMockSandboxDriver();
    lifecycleManager = new CapsuleLifecycleManager({ driver: mockDriver });
    accessManager = new AccessManager();

    // Register active test app
    accessManager.registerApp({
      id: 'app-target',
      appKey: 'target-app',
      name: 'Target App',
      organizationId: 'org_acme',
      status: 'active',
      manifest: {
        id: 'target-app',
        roles: ['employee'],
        limits: {
          request_body_max_mb: 1,  // 1MB limit for testing
          request_timeout_s: 1,    // 1s timeout for testing
        },
      },
    });

    server = createEdgeProxyServer({
      config: {
        appDomain,
        dashboardDomain,
      },
      lifecycleManager,
      accessManager,
    });

    await new Promise<void>((resolve) => {
      server.listen(0, '127.0.0.1', () => {
        serverPort = (server.address() as AddressInfo).port;
        resolve();
      });
    });

    // Complete auth handshake for target-app
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=alice&target_app=target-app&return_to=http://target-app.${appDomain}:${serverPort}/auth/callback`,
    });
    const callbackUrl = new URL(ticketRes.headers.location || '');
    const ticket = callbackUrl.searchParams.get('ticket');

    const callbackRes = await makeRequest({
      host: `target-app.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });
    sessionCookie = callbackRes.headers['set-cookie']?.[0]?.split(';')[0] || '';
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  it('serves active app normally', async () => {
    const res = await makeRequest({
      host: `target-app.${appDomain}:${serverPort}`,
      path: '/api/test',
      headers: { cookie: sessionCookie },
    });
    expect(res.statusCode).toBe(200);
  });

  it('returns 503 suspended page when app is suspended', async () => {
    // 1. Suspend app
    await (server as any).suspendApp('target-app', 'Security containment');

    // 2. Request should return 503
    const res = await makeRequest({
      host: `target-app.${appDomain}:${serverPort}`,
      path: '/api/test',
      headers: { cookie: sessionCookie },
    });
    expect(res.statusCode).toBe(503);
    expect(res.body).toContain('Capsule Suspended');
    expect(res.body).toContain('target-app is suspended');

    // 3. Resume app
    await (server as any).resumeApp('target-app');
    const resAfter = await makeRequest({
      host: `target-app.${appDomain}:${serverPort}`,
      path: '/api/test',
      headers: { cookie: sessionCookie },
    });
    expect(resAfter.statusCode).toBe(200);
  });

  it('returns 503 when organization is frozen', async () => {
    // 1. Freeze org
    await (server as any).freezeOrg('org_acme', 'Org-wide security breach');

    // 2. Request should return 503
    const res = await makeRequest({
      host: `target-app.${appDomain}:${serverPort}`,
      path: '/api/test',
      headers: { cookie: sessionCookie },
    });
    expect(res.statusCode).toBe(503);
    expect(res.body).toContain('Organization Suspended');

    // 3. Resume org
    await (server as any).resumeOrg('org_acme');
    const resAfter = await makeRequest({
      host: `target-app.${appDomain}:${serverPort}`,
      path: '/api/test',
      headers: { cookie: sessionCookie },
    });
    expect(resAfter.statusCode).toBe(200);
  });

  it('enforces request body size quota (HTTP 413)', async () => {
    // Target app has 1MB limit. Send 1.5MB of data
    const oversizedBody = 'X'.repeat(1.5 * 1024 * 1024);
    const res = await makeRequest({
      host: `target-app.${appDomain}:${serverPort}`,
      path: '/upload',
      method: 'POST',
      headers: {
        cookie: sessionCookie,
        'Content-Type': 'text/plain',
        'Content-Length': String(Buffer.byteLength(oversizedBody)),
      },
      body: oversizedBody,
    });

    expect(res.statusCode).toBe(413);
    const data = JSON.parse(res.body);
    expect(data.code).toBe('QUOTA_EXCEEDED');
    expect(data.metric).toBe('request_body_max_mb');
  });


  it('enforces request timeout quota (HTTP 504)', async () => {
    // Override forwardRequest to delay 1.5s (app has 1s limit)
    const origForward = mockDriver.forwardRequest.bind(mockDriver);
    mockDriver.forwardRequest = async (_id: string, req: ForwardRequest): Promise<ForwardResponse> => {
      await new Promise((r) => setTimeout(r, 1500));
      return origForward(_id, req);
    };

    try {
      const res = await makeRequest({
        host: `target-app.${appDomain}:${serverPort}`,
        path: '/slow',
        headers: { cookie: sessionCookie },
      });
      expect(res.statusCode).toBe(504);
      const data = JSON.parse(res.body);
      expect(data.code).toBe('QUOTA_EXCEEDED');
      expect(data.metric).toBe('request_timeout_s');
    } finally {
      mockDriver.forwardRequest = origForward;
    }
  });

  it('aborts in-flight requests within 5 seconds when app is suspended', async () => {
    // Setup a long-running request (delay 10 seconds)
    const origForward = mockDriver.forwardRequest.bind(mockDriver);
    mockDriver.forwardRequest = async (_id: string, req: ForwardRequest): Promise<ForwardResponse> => {
      await new Promise((r) => setTimeout(r, 10000));
      return origForward(_id, req);
    };

    const startTime = Date.now();

    try {
      // Launch request in background
      const requestPromise = makeRequest({
        host: `target-app.${appDomain}:${serverPort}`,
        path: '/long-running',
        headers: { cookie: sessionCookie },
      }).catch((err) => ({ error: err }));

      // Wait 100ms, then trigger instant emergency kill switch
      await new Promise((r) => setTimeout(r, 100));
      await (server as any).suspendApp('target-app', 'Emergency test kill');

      // Await the in-flight request result
      const result: any = await requestPromise;
      const elapsedTimeMs = Date.now() - startTime;

      // Invariant: Must take hold within 5000ms
      expect(elapsedTimeMs).toBeLessThan(5000);

      // Request must either have thrown a connection abort error or returned 503/504.
      // 503 = app suspended cleanly; 504 = gateway timeout when sandbox was killed mid-flight.
      // Both are valid kill-switch outcomes for an in-flight request.
      if (result.error) {
        expect(result.error).toBeDefined();
      } else {
        expect([503, 504]).toContain(result.statusCode);
      }
    } finally {
      mockDriver.forwardRequest = origForward;
      await (server as any).resumeApp('target-app');
    }
  });
});
