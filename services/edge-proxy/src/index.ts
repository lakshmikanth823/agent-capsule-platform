/**
 * @capsule/edge-proxy
 *
 * Edge reverse proxy providing per-Capsule origin isolation,
 * hostname-based routing, per-app host-only authentication handshake,
 * access control, role mapping, wake-on-request container management,
 * signed identity injection with key rotation, and security headers.
 */
import http from 'node:http';
import path from 'node:path';
import { loadConfig, type ProxyConfig } from './config.js';
import { signJwt, verifyJwt } from './crypto.js';
import {
  createHostOnlyCookie,
  getSessionFromRequest,
  createSessionToken,
  type AppSession,
} from './session.js';
import {
  renderAppNotFoundPage,
  renderNotAuthorizedPage,
  renderPlatformLoginPage,
} from './pages.js';
import { AccessManager, type UserContext } from './access.js';
import {
  CapsuleLifecycleManager,
  DevMockSandboxDriver,
  type ForwardRequest,
} from '@capsule/sandbox-driver';

export * from './config.js';
export * from './crypto.js';
export * from './session.js';
export * from './access.js';
export * from './pages.js';

export function extractSubdomainCapsuleId(
  hostname: string,
  appDomain = 'apps.localhost'
): string | null {
  const hostWithoutPort = hostname.split(':')[0].toLowerCase();
  const normalizedAppDomain = appDomain.toLowerCase();

  if (hostWithoutPort.endsWith(`.${normalizedAppDomain}`)) {
    const subdomain = hostWithoutPort.slice(0, -(normalizedAppDomain.length + 1));
    return subdomain || null;
  }
  return null;
}

export function applySecurityHeaders(res: http.ServerResponse, isProduction = false): void {
  res.setHeader(
    'Content-Security-Policy',
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
  );
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');

  if (isProduction) {
    res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  }
}

function readRequestBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
    });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

export function createEdgeProxyServer(options?: {
  config?: Partial<ProxyConfig>;
  lifecycleManager?: CapsuleLifecycleManager;
  accessManager?: AccessManager;
}): http.Server {
  const baseConfig = loadConfig();
  const config: ProxyConfig = { ...baseConfig, ...(options?.config || {}) };

  const accessManager = options?.accessManager || new AccessManager();
  const lifecycleManager =
    options?.lifecycleManager ||
    new CapsuleLifecycleManager({
      driver: new DevMockSandboxDriver(),
    });

  // Seed default sample app into access manager if empty
  if (!accessManager.getApp('leave-tracker')) {
    accessManager.registerApp({
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
      dataDir: path.resolve('data/capsules/leave-tracker/data'),
    });
  }

  const server = http.createServer(async (req, res) => {
    applySecurityHeaders(res, config.isProduction);

    const hostHeader = req.headers.host || 'localhost';
    const hostWithoutPort = hostHeader.split(':')[0].toLowerCase();
    const url = new URL(req.url || '/', `http://${hostHeader}`);
    const pathname = url.pathname;

    // 1. Route: Dashboard / Platform Domain
    if (hostWithoutPort === config.dashboardDomain.toLowerCase()) {
      // Platform Login Page
      if (pathname === '/auth/login') {
        const targetApp = url.searchParams.get('target_app') || 'leave-tracker';
        const returnTo = url.searchParams.get('return_to') || `http://${targetApp}.${config.appDomain}:${config.port}/auth/callback`;
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(renderPlatformLoginPage(targetApp, returnTo));
        return;
      }

      // Platform Auth Ticket Issue (Mock IdP / SSO Handshake)
      if (pathname === '/auth/ticket') {
        const userChoice = url.searchParams.get('user') || 'alice';
        const targetApp = url.searchParams.get('target_app') || 'leave-tracker';
        const returnTo = url.searchParams.get('return_to') || `http://${targetApp}.${config.appDomain}:${config.port}/auth/callback`;

        // Predefined mock users matching Prompt 05 & 06
        const mockUsers: Record<string, UserContext> = {
          alice: {
            id: 'usr_alice_123',
            email: 'alice@example.com',
            orgId: 'org_acme',
            platformRole: 'owner',
            groups: ['engineering'],
          },
          bob: {
            id: 'usr_bob_456',
            email: 'bob@example.com',
            orgId: 'org_acme',
            platformRole: 'user',
            groups: ['finance'],
          },
          charlie: {
            id: 'usr_charlie_789',
            email: 'charlie@other.com',
            orgId: 'org_other',
            platformRole: 'user',
            groups: ['sales'],
          },
        };

        const user = mockUsers[userChoice] || mockUsers.alice;

        // Generate short-lived (60s) single-use handshake ticket
        const ticketPayload = {
          sub: user.id,
          email: user.email,
          org_id: user.orgId,
          platform_role: user.platformRole,
          groups: user.groups,
          target_app: targetApp,
          exp: Math.floor(Date.now() / 1000) + 60,
        };
        const ticket = signJwt(ticketPayload, config.sessionSecret);

        // Redirect back to app origin's /auth/callback
        const redirectUrl = new URL(returnTo);
        redirectUrl.searchParams.set('ticket', ticket);
        redirectUrl.searchParams.set('return_to', '/');

        res.writeHead(302, { Location: redirectUrl.toString() });
        res.end();
        return;
      }

      // Platform Root
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ platform: 'Software Capsule Platform', domain: config.dashboardDomain }));
      return;
    }

    // 2. Route: App Subdomain (<app>.<APP_DOMAIN>)
    const appKey = extractSubdomainCapsuleId(hostHeader, config.appDomain);
    if (!appKey) {
      // Hostname does not match an app subdomain or platform domain
      res.writeHead(404, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(renderAppNotFoundPage('Unknown', hostHeader));
      return;
    }

    // A. App Auth Callback (Token Exchange Handshake)
    if (pathname === '/auth/callback') {
      const ticket = url.searchParams.get('ticket');
      const returnTo = url.searchParams.get('return_to') || '/';

      if (!ticket) {
        res.writeHead(400, { 'Content-Type': 'text/plain' });
        res.end('Missing ticket in callback.');
        return;
      }

      const verified = verifyJwt<any>(ticket, { default: config.sessionSecret });
      if (!verified || verified.payload.target_app !== appKey) {
        res.writeHead(401, { 'Content-Type': 'text/plain' });
        res.end('Invalid, expired, or mismatched ticket.');
        return;
      }

      const ticketUser: UserContext = {
        id: verified.payload.sub,
        email: verified.payload.email,
        orgId: verified.payload.org_id,
        platformRole: verified.payload.platform_role,
        groups: verified.payload.groups,
      };

      // Check app existence and access
      const app = accessManager.getApp(appKey);
      if (!app) {
        res.writeHead(404, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(renderAppNotFoundPage(appKey, hostHeader));
        return;
      }

      const access = accessManager.evaluateAccess(ticketUser, app);
      if (!access.allowed) {
        res.writeHead(403, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(renderNotAuthorizedPage(appKey, ticketUser.email, ticketUser.orgId, access.reason));
        return;
      }

      // Issue host-only cookie for this specific app origin
      const sessionData: Omit<AppSession, 'iat' | 'exp'> = {
        sub: ticketUser.id,
        email: ticketUser.email,
        org_id: ticketUser.orgId,
        app_key: appKey,
        platform_role: access.platformRole || 'user',
        app_roles: access.appRoles || ['employee'],
        groups: ticketUser.groups,
      };

      const sessionToken = createSessionToken(sessionData, config.sessionSecret);
      const hostOnlyCookie = createHostOnlyCookie(sessionToken, config.isProduction);

      res.writeHead(302, {
        'Set-Cookie': hostOnlyCookie,
        Location: returnTo,
      });
      res.end();
      return;
    }

    // B. Check Session for App Request
    const session = getSessionFromRequest(req.headers.cookie, appKey, config.sessionSecret);
    if (!session) {
      // Unauthenticated: Redirect to Platform Login Handshake
      const returnUrl = `http://${appKey}.${config.appDomain}:${config.port}/auth/callback`;
      const loginUrl = `http://${config.dashboardDomain}:${config.port}/auth/login?target_app=${appKey}&return_to=${encodeURIComponent(returnUrl)}`;
      res.writeHead(302, { Location: loginUrl });
      res.end();
      return;
    }

    // C. Check App Existence and Authorization
    const app = accessManager.getApp(appKey);
    if (!app) {
      res.writeHead(404, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(renderAppNotFoundPage(appKey, hostHeader));
      return;
    }

    const currentUser: UserContext = {
      id: session.sub,
      email: session.email,
      orgId: session.org_id,
      platformRole: session.platform_role,
      groups: session.groups,
    };

    const access = accessManager.evaluateAccess(currentUser, app);
    if (!access.allowed) {
      res.writeHead(403, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(renderNotAuthorizedPage(appKey, currentUser.email, currentUser.orgId, access.reason));
      return;
    }

    // D. Wake Capsule & Forward Request with Signed Identity Header
    try {
      const rawBody = await readRequestBody(req);

      // Sign identity token using active key with key rotation support (kid)
      const now = Math.floor(Date.now() / 1000);
      const identityPayload = {
        iss: 'platform',
        aud: `capsule:${app.id}`,
        sub: session.sub,
        email: session.email,
        org_id: session.org_id,
        groups: session.groups || [],
        roles: access.appRoles || session.app_roles || [],
        iat: now,
        exp: now + 300, // 5 minutes validity
      };

      const activeSecret =
        config.signingKeys[config.activeKeyId] || Object.values(config.signingKeys)[0];
      const signedIdentityToken = signJwt(identityPayload, activeSecret, config.activeKeyId);

      const forwardHeaders: Record<string, string> = {};
      for (const [k, v] of Object.entries(req.headers)) {
        if (v && typeof v === 'string') forwardHeaders[k] = v;
      }
      // Inject signed identity context
      forwardHeaders['x-capsule-identity'] = signedIdentityToken;

      const forwardReq: ForwardRequest = {
        method: req.method || 'GET',
        path: pathname + (url.search || ''),
        headers: forwardHeaders,
        body: rawBody,
      };

      // Prepare sandbox spec
      const spec = await lifecycleManager.prepareCapsule({
        capsuleId: app.id,
        versionId: app.currentVersionId || 'v1',
        appKey: app.appKey,
        bundlePath: app.bundlePath || path.resolve(`examples/${app.appKey}`),
        customDataDir: app.dataDir,
        manifest: app.manifest,
      });

      // Wake-on-Request and forward
      const forwardRes = await lifecycleManager.handleRequest(spec, forwardReq);

      // Return capsule response to client
      for (const [hk, hv] of Object.entries(forwardRes.headers)) {
        if (hk.toLowerCase() !== 'content-security-policy' && hk.toLowerCase() !== 'x-frame-options') {
          res.setHeader(hk, hv);
        }
      }
      res.writeHead(forwardRes.statusCode);
      res.end(forwardRes.body);
    } catch (err: any) {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Bad Gateway', details: err.message || err }));
    }
  });

  return server;
}
