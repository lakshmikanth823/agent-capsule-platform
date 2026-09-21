import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import { AddressInfo } from 'node:net';
import path from 'node:path';
import {
  createEdgeProxyServer,
  AccessManager,
  verifyJwt,
  type AppMetadata,
  type UserContext,
} from '../src/index.js';
import {
  DevMockSandboxDriver,
  CapsuleLifecycleManager,
  type ForwardRequest,
} from '@capsule/sandbox-driver';

describe('Edge Proxy - Sharing, Roles, and Immediate Revocation', () => {
  let server: http.Server;
  let serverPort: number;
  let mockDriver: DevMockSandboxDriver;
  let lifecycleManager: CapsuleLifecycleManager;
  let accessManager: AccessManager;

  const appDomain = 'apps.localhost';
  const dashboardDomain = 'platform.localhost';

  const sampleApp: AppMetadata = {
    id: 'app-leave-tracker',
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
    dataDir: path.resolve('data/capsules/leave-tracker-sharing/data'),
    defaultScope: 'restricted', // Only explicit shares or owner allowed
  };

  beforeAll(async () => {
    mockDriver = new DevMockSandboxDriver();
    lifecycleManager = new CapsuleLifecycleManager({ driver: mockDriver });
    accessManager = new AccessManager();

    accessManager.registerApp(sampleApp);

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

  it("should enforce each role's allowed and denied access", async () => {
    let capturedReq: ForwardRequest | null = null;
    mockDriver.setMockResponse('/api/identity', (req) => {
      capturedReq = req;
      return {
        statusCode: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ok: true }),
      };
    });

    // 1. Owner (Alice) has full access
    const aliceTicketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=alice&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const aliceTicket = new URL(aliceTicketRes.headers.location || '').searchParams.get('ticket');
    const aliceCallback = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${aliceTicket}&return_to=/`,
    });
    const aliceCookie = aliceCallback.headers['set-cookie']?.[0]?.split(';')[0] || '';

    const aliceReq = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: '/api/identity',
      headers: { cookie: aliceCookie },
    });
    expect(aliceReq.statusCode).toBe(200);

    // Verify Owner identity payload has all declared roles
    const identityJwt = capturedReq!.headers?.['x-capsule-identity'];
    const keys = { 'key-2026-09': 'dev-identity-secret-key-must-be-32-bytes-long!' };
    const verifiedAlice = verifyJwt<any>(identityJwt!, keys);
    expect(verifiedAlice?.payload.sub).toBe('usr_alice_123');
    expect(verifiedAlice?.payload.roles).toEqual(['employee', 'manager', 'hr']);

    // 2. User with no access (Charlie from other org) is blocked
    const charlieTicketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=charlie&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const charlieTicket = new URL(charlieTicketRes.headers.location || '').searchParams.get('ticket');
    const charlieCallback = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${charlieTicket}&return_to=/`,
    });
    expect(charlieCallback.statusCode).toBe(403);
    expect(charlieCallback.body).toContain('Access Denied');
  });

  it('should handle group membership changes for group-based sharing', async () => {
    let capturedReq: ForwardRequest | null = null;
    mockDriver.setMockResponse('/api/group-test', (req) => {
      capturedReq = req;
      return {
        statusCode: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ok: true }),
      };
    });

    // Share app with group 'finance' assigning role 'hr'
    accessManager.addShare({
      appKey: 'leave-tracker',
      groupName: 'finance',
      appRole: 'hr',
    });

    // Bob has group 'finance' (from mockUsers in index.ts)
    const bobTicketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=bob&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const bobTicket = new URL(bobTicketRes.headers.location || '').searchParams.get('ticket');
    const bobCallback = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${bobTicket}&return_to=/`,
    });
    expect(bobCallback.statusCode).toBe(302);
    const bobCookie = bobCallback.headers['set-cookie']?.[0]?.split(';')[0] || '';

    const bobReq = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: '/api/group-test',
      headers: { cookie: bobCookie },
    });
    expect(bobReq.statusCode).toBe(200);

    // Verify Bob received role 'hr' from the 'finance' group share
    const identityJwt = capturedReq!.headers?.['x-capsule-identity'];
    const keys = { 'key-2026-09': 'dev-identity-secret-key-must-be-32-bytes-long!' };
    const verifiedBob = verifyJwt<any>(identityJwt!, keys);
    expect(verifiedBob?.payload.sub).toBe('usr_bob_456');
    expect(verifiedBob?.payload.roles).toContain('hr');
  });

  it('Acceptance: owner shares app with colleague, colleague opens it, unsharing blocks them immediately', async () => {
    // 1. Owner shares sample app with colleague Bob (assigning role 'manager')
    const bobShare = accessManager.addShare({
      appKey: 'leave-tracker',
      userEmail: 'bob@example.com',
      userId: 'usr_bob_456',
      appRole: 'manager',
    });
    expect(bobShare.status).toBe('active');

    // 2. Colleague Bob opens the app URL through edge proxy
    // Step 2a: Initial request redirects to login
    const initRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: '/',
    });
    expect(initRes.statusCode).toBe(302);

    // Step 2b: Bob logs in and gets ticket
    const ticketRes = await makeRequest({
      host: `${dashboardDomain}:${serverPort}`,
      path: `/auth/ticket?user=bob&target_app=leave-tracker&return_to=http://leave-tracker.${appDomain}:${serverPort}/auth/callback`,
    });
    const ticket = new URL(ticketRes.headers.location || '').searchParams.get('ticket');

    // Step 2c: Callback sets host-only cookie
    const callbackRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: `/auth/callback?ticket=${ticket}&return_to=/`,
    });
    expect(callbackRes.statusCode).toBe(302);
    const bobSessionCookie = callbackRes.headers['set-cookie']?.[0]?.split(';')[0] || '';
    expect(bobSessionCookie).toContain('capsule_session=');

    // Step 2d: Bob opens the app with his open session -> HTTP 200
    mockDriver.setMockResponse('/health', () => ({
      statusCode: 200,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ status: 'healthy', user: 'bob' }),
    }));

    const openSessionRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: '/health',
      headers: { cookie: bobSessionCookie },
    });
    expect(openSessionRes.statusCode).toBe(200);

    // 3. Owner unshares / revokes Bob's share
    const revoked = accessManager.revokeShare(bobShare.id);
    expect(revoked).toBe(true);

    // 4. Bob sends next request with the existing open session cookie
    // Revocation MUST take effect immediately: 403 Forbidden and cookie cleared
    const blockedRes = await makeRequest({
      host: `leave-tracker.${appDomain}:${serverPort}`,
      path: '/health',
      headers: { cookie: bobSessionCookie },
    });

    expect(blockedRes.statusCode).toBe(403);
    expect(blockedRes.body).toContain('Access Denied');
    expect(blockedRes.body).toContain('Access to this capsule has been revoked');

    // Cookie must be cleared
    const clearCookieHeader = blockedRes.headers['set-cookie']?.[0] || '';
    expect(clearCookieHeader).toContain('capsule_session=;');
    expect(clearCookieHeader).toContain('Max-Age=0');
  });
});
