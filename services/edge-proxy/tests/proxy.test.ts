import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import { AddressInfo } from 'node:net';
import {
  createEdgeProxyServer,
  extractSubdomainCapsuleId,
  signJwt,
  verifyJwt,
  AccessManager,
} from '../src/index.js';
import {
  DevMockSandboxDriver,
  DockerDevDriver,
  CapsuleLifecycleManager,
  isDockerAvailable,
  type ForwardRequest,
} from '@capsule/sandbox-driver';
import path from 'node:path';

const hasDocker = isDockerAvailable();

describe('Edge Proxy Service', () => {
  let server: http.Server;
  let serverPort: number;
  let mockDriver: DevMockSandboxDriver;
  let lifecycleManager: CapsuleLifecycleManager;
  let accessManager: AccessManager;

  const appDomain = 'apps.localhost';
  const dashboardDomain = 'platform.localhost';

  beforeAll(async () => {
    mockDriver = new DevMockSandboxDriver();
    lifecycleManager = new CapsuleLifecycleManager({ driver: mockDriver });
    accessManager = new AccessManager();

    // Register test apps
    accessManager.registerApp({
      id: 'app-leave-tracker',
      appKey: 'leave-tracker',
      name: 'Leave Tracker',
      organizationId: 'org_acme',
      status: 'active',
      manifest: {
        id: 'leave-tracker',
        roles: ['employee', 'manager', 'hr'],
        capabilities: {
          identity: true,
        },
      },
    });

    accessManager.registerApp({
      id: 'app-expenses',
      appKey: 'expenses',
      name: 'Expenses',
      organizationId: 'org_acme',
      status: 'active',
      manifest: {
        id: 'expenses',
        roles: ['submitter', 'approver'],
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
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

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

  it('should extract capsule id from subdomain on apps.localhost', () => {
    expect(extractSubdomainCapsuleId('leave-tracker.apps.localhost:8080', 'apps.localhost')).toBe(
      'leave-tracker'
    );
    expect(extractSubdomainCapsuleId('team-dashboard.apps.localhost', 'apps.localhost')).toBe(
      'team-dashboard'
    );
    expect(extractSubdomainCapsuleId('platform.localhost:8080', 'apps.localhost')).toBeNull();
    expect(extractSubdomainCapsuleId('apps.localhost:8080', 'apps.localhost')).toBeNull();
  });

  it('should redirect unauthenticated requests to platform login with target_app and return_to', async () => {
    const res = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: '/',
    });

    expect(res.statusCode).toBe(302);
    const location = res.headers.location || '';
    expect(location).toContain(`http://${dashboardDomain}`);
    expect(location).toContain('/auth/login');
    expect(location).toContain('target_app=leave-tracker');
  });

  it('should complete auth handshake and issue host-only session cookie (no Domain attribute)', async () => {
    // 1. Get ticket from platform
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=alice&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    expect(ticketRes.statusCode).toBe(302);
    const callbackUrl = new URL(ticketRes.headers.location || '');
    const ticket = callbackUrl.searchParams.get('ticket');
    expect(ticket).toBeTruthy();

    // 2. Callback on app origin
    const callbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });
    expect(callbackRes.statusCode).toBe(302);
    expect(callbackRes.headers.location).toBe('/');

    // 3. Verify Host-Only Cookie
    const setCookie = callbackRes.headers['set-cookie']?.[0] || '';
    expect(setCookie).toContain('capsule_session=');
    expect(setCookie).toContain('Path=/');
    expect(setCookie).toContain('HttpOnly');
    expect(setCookie).toContain('SameSite=Lax');
    // Security check: Must NOT have Domain= attribute to be strictly host-only per RFC 6265
    expect(setCookie).not.toContain('Domain=');
  });

  it('should not share session cookies across two different apps (origin isolation)', async () => {
    // 1. Obtain session cookie for leave-tracker
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=alice&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const callbackUrl = new URL(ticketRes.headers.location || '');
    const ticket = callbackUrl.searchParams.get('ticket');

    const callbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });
    const leaveTrackerCookie = callbackRes.headers['set-cookie']?.[0]?.split(';')[0] || '';

    // 2. Attempt to use leave-tracker's cookie on expenses app
    const expensesRes = await makeRequest({
      host: `expenses.${appDomain}:${serverPort}`,
      path: '/',
      headers: {
        cookie: leaveTrackerCookie,
      },
    });

    // Must be rejected and redirected to login for expenses because cookie belongs to leave-tracker
    expect(expensesRes.statusCode).toBe(302);
    expect(expensesRes.headers.location).toContain('target_app=expenses');
  });

  it('should block unauthorized user with 403 clear error page', async () => {
    // Charlie is from 'org_other' while leave-tracker belongs to 'org_acme'
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=charlie&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const callbackUrl = new URL(ticketRes.headers.location || '');
    const ticket = callbackUrl.searchParams.get('ticket');

    const callbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });

    expect(callbackRes.statusCode).toBe(403);
    expect(callbackRes.body).toContain('Access Denied');
    expect(callbackRes.body).toContain('charlie@other.com');
  });

  it('should return clear 404 page for unknown app', async () => {
    // Request with dummy session on non-existent app
    const res = await makeRequest({
      host: `non-existent.${appDomain}:${serverPort}`,
      path: '/',
    });
    expect(res.statusCode).toBe(302); // Redirects to login with target_app=non-existent

    // If ticket is presented for non-existent app
    const ticket = signJwt(
      {
        sub: 'usr_alice',
        email: 'alice@example.com',
        org_id: 'org_acme',
        target_app: 'non-existent',
        exp: Math.floor(Date.now() / 1000) + 60,
      },
      'dev-session-secret-change-in-production-32-chars!'
    );

    const callbackRes = await makeRequest({
      host: `non-existent.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}`,
    });
    expect(callbackRes.statusCode).toBe(404);
    expect(callbackRes.body).toContain('Capsule Not Found');
  });

  it('should inject security headers on every response', async () => {
    const res = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: '/auth/login',
    });

    expect(res.headers['content-security-policy']).toBeDefined();
    expect(res.headers['x-frame-options']).toBe('DENY');
    expect(res.headers['x-content-type-options']).toBe('nosniff');
    expect(res.headers['referrer-policy']).toBe('strict-origin-when-cross-origin');
  });

  it('should forward request with signed identity header supporting key rotation', async () => {
    let capturedForwardReq: ForwardRequest | null = null;
    mockDriver.setMockResponse('/api/test', (req) => {
      capturedForwardReq = req;
      return {
        statusCode: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ok: true }),
      };
    });

    // Obtain session for Alice
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=alice&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const callbackUrl = new URL(ticketRes.headers.location || '');
    const ticket = callbackUrl.searchParams.get('ticket');

    const callbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });
    const cookie = callbackRes.headers['set-cookie']?.[0]?.split(';')[0] || '';

    // Make request to /api/test
    const apiRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: '/api/test',
      headers: { cookie },
    });
    expect(apiRes.statusCode).toBe(200);

    expect(capturedForwardReq).not.toBeNull();
    const identityHeader = capturedForwardReq!.headers?.['x-capsule-identity'];
    expect(identityHeader).toBeDefined();

    // Verify identity JWT signature and key rotation
    const keys = {
      'key-2026-09': 'dev-identity-secret-key-must-be-32-bytes-long!',
      'key-2026-08': 'older-identity-secret-key-for-rotation-testing!',
    };

    const verified = verifyJwt<any>(identityHeader!, keys);
    expect(verified).not.toBeNull();
    expect(verified?.header.kid).toBe('key-2026-09');
    expect(verified?.payload.sub).toBe('usr_alice_123');
    expect(verified?.payload.org_id).toBe('org_acme');
    expect(verified?.payload.aud).toBe('capsule:app-leave-tracker');
    expect(verified?.payload.roles).toEqual(['employee', 'manager', 'hr']);

    // Tampered header rejected
    const tampered = identityHeader + 'xyz';
    expect(verifyJwt(tampered, keys)).toBeNull();

    // Expired token rejected
    const expiredToken = signJwt(
      { sub: 'usr_test', exp: Math.floor(Date.now() / 1000) - 10 },
      keys['key-2026-09'],
      'key-2026-09'
    );
    expect(verifyJwt(expiredToken, keys)).toBeNull();
  });
});

describe.skipIf(!hasDocker)('Edge Proxy Acceptance Test (with DockerDevDriver & Leave Tracker App)', () => {
  let server: http.Server;
  let serverPort: number;
  let dockerDriver: DockerDevDriver;
  let lifecycleManager: CapsuleLifecycleManager;
  let accessManager: AccessManager;
  const appDomain = 'apps.localhost';
  const dashboardDomain = 'platform.localhost';

  beforeAll(async () => {
    dockerDriver = new DockerDevDriver();
    lifecycleManager = new CapsuleLifecycleManager({ driver: dockerDriver });
    accessManager = new AccessManager();

    // Register the leave-tracker sample app
    accessManager.registerApp({
      id: 'leave-tracker',
      appKey: 'leave-tracker',
      name: 'Leave Tracker',
      organizationId: 'org_acme',
      status: 'active',
      manifest: {
        id: 'leave-tracker',
        roles: ['employee', 'manager', 'hr'],
        capabilities: { db: { type: 'sqlite' }, identity: true },
      },
      bundlePath: path.resolve('examples/leave-tracker'),
      dataDir: path.resolve('data/capsules/leave-tracker-acceptance/data'),
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
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await lifecycleManager.destroy('leave-tracker').catch(() => {});
  });

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

  it('Acceptance: opening the sample app URL in browser logs in with mock IdP and shows identity', async () => {
    // 1. Browser visits sample app URL
    const initialRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: '/',
    });
    expect(initialRes.statusCode).toBe(302);
    expect(initialRes.headers.location).toContain('/auth/login?target_app=leave-tracker');

    // 2. User logs in with mock IdP (selects Alice)
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=alice&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    expect(ticketRes.statusCode).toBe(302);
    const callbackUrl = new URL(ticketRes.headers.location || '');
    const ticket = callbackUrl.searchParams.get('ticket');
    expect(ticket).toBeTruthy();

    // 3. Handshake callback sets host-only cookie
    const callbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });
    expect(callbackRes.statusCode).toBe(302);
    const cookie = callbackRes.headers['set-cookie']?.[0]?.split(';')[0] || '';
    expect(cookie).toContain('capsule_session=');

    // 4. Request /api/identity through edge proxy
    const idRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: '/api/identity',
      headers: { cookie },
    });
    expect(idRes.statusCode).toBe(200);

    // 5. Request HTML root view showing identity
    const htmlRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: '/',
      headers: { cookie },
    });
    expect(htmlRes.statusCode).toBe(200);
    expect(htmlRes.headers['content-security-policy']).toBeDefined();
    expect(htmlRes.headers['x-frame-options']).toBe('DENY');
    expect(htmlRes.body).toContain('Leave Tracker Capsule');
  }, 45000);
});
