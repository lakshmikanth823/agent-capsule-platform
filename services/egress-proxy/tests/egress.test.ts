import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest';
import http from 'node:http';
import net from 'node:net';
import {
  createEgressProxyServer,
  EgressPolicyManager,
  EgressLogger,
  isPrivateOrBlockedIp,
  resolveAndValidateDestination,
  evaluateEgressPolicy,
} from '../src/index.js';

describe('Egress Proxy & SSRF Prevention Suite', () => {
  let proxyServer: http.Server;
  let targetHttpServer: http.Server;
  let policyManager: EgressPolicyManager;
  let logger: EgressLogger;

  const PROXY_PORT = 19080;
  const TARGET_PORT = 19081;

  beforeAll(async () => {
    policyManager = new EgressPolicyManager();
    logger = new EgressLogger();

    // Mock target HTTP server to receive forwarded requests
    targetHttpServer = http.createServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok', path: req.url, host: req.headers.host }));
    });
    await new Promise((resolve) => targetHttpServer.listen(TARGET_PORT, '127.0.0.1', () => resolve(true)));

    proxyServer = createEgressProxyServer({
      policyManager,
      logger,
      // For general tests, resolve test domains to our local target port or public dummy
      dnsResolver: {
        lookup: async (hostname: string) => {
          if (hostname === 'api.example.com' || hostname === 'safe.example.com') {
            return [{ address: '93.184.216.34', family: 4 }];
          }
          if (hostname === 'rebinding.bad.com') {
            // DNS rebinding trick: resolves to loopback IP
            return [{ address: '127.0.0.1', family: 4 }];
          }
          if (hostname === 'metadata.google.internal' || hostname === 'cloud-metadata.com') {
            return [{ address: '169.254.169.254', family: 4 }];
          }
          return [{ address: '93.184.216.34', family: 4 }];
        },
      },
    });
    await new Promise((resolve) => proxyServer.listen(PROXY_PORT, '127.0.0.1', () => resolve(true)));
  });

  afterAll(async () => {
    await new Promise((resolve) => proxyServer.close(resolve));
    await new Promise((resolve) => targetHttpServer.close(resolve));
  });

  beforeEach(() => {
    logger.clear();
    policyManager.clear();
  });

  describe('1. SSRF & IP Blocklist Checks', () => {
    it('should block IPv4 loopback and private ranges', () => {
      expect(isPrivateOrBlockedIp('127.0.0.1').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('127.0.0.254').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('10.0.0.1').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('10.254.254.254').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('172.16.0.1').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('172.31.255.255').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('192.168.1.1').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('192.168.254.254').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('0.0.0.0').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('100.64.0.1').blocked).toBe(true);
    });

    it('should block cloud metadata and link-local addresses', () => {
      expect(isPrivateOrBlockedIp('169.254.169.254').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('169.254.1.1').blocked).toBe(true);
    });

    it('should block IPv6 equivalents (loopback, unique local, link-local, IPv4-mapped)', () => {
      expect(isPrivateOrBlockedIp('::1').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('::').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('fc00::1').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('fd00::1').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('fe80::1').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('::ffff:127.0.0.1').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('::ffff:169.254.169.254').blocked).toBe(true);
      expect(isPrivateOrBlockedIp('::ffff:10.0.0.1').blocked).toBe(true);
    });

    it('should allow valid public IP addresses', () => {
      expect(isPrivateOrBlockedIp('8.8.8.8').blocked).toBe(false);
      expect(isPrivateOrBlockedIp('93.184.216.34').blocked).toBe(false);
      expect(isPrivateOrBlockedIp('1.1.1.1').blocked).toBe(false);
    });

    it('should block known internal hostnames', async () => {
      const localhostCheck = await resolveAndValidateDestination('localhost');
      expect(localhostCheck.valid).toBe(false);
      expect(localhostCheck.reason).toContain('Blocked internal hostname');

      const metadataCheck = await resolveAndValidateDestination('metadata.google.internal');
      expect(metadataCheck.valid).toBe(false);
    });

    it('should block DNS rebinding tricks at connection time', async () => {
      const rebindingResolver = {
        lookup: async () => [{ address: '127.0.0.1', family: 4 }],
      };
      const result = await resolveAndValidateDestination('rebinding.example.com', rebindingResolver);
      expect(result.valid).toBe(false);
      expect(result.reason).toContain('Loopback address');
    });
  });

  describe('2. Egress Policy & Default-Deny', () => {
    it('should deny all outbound traffic by default when no egress is declared', () => {
      const emptyPolicy = {
        appKey: 'unprivileged-app',
        appAllowlist: [],
      };

      const result = evaluateEgressPolicy('api.example.com', 443, emptyPolicy);
      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('Default deny');
    });

    it('should allow declared domains and ports', () => {
      const policy = {
        appKey: 'leave-tracker',
        appAllowlist: [
          { host: 'api.slack.com', ports: [443] },
          { host: '*.google.com', ports: [443, 80] },
        ],
      };

      // Exact match
      const r1 = evaluateEgressPolicy('api.slack.com', 443, policy);
      expect(r1.allowed).toBe(true);

      // Port mismatch
      const r2 = evaluateEgressPolicy('api.slack.com', 8080, policy);
      expect(r2.allowed).toBe(false);

      // Wildcard subdomain match
      const r3 = evaluateEgressPolicy('sheets.google.com', 443, policy);
      expect(r3.allowed).toBe(true);

      // Unlisted domain
      const r4 = evaluateEgressPolicy('api.github.com', 443, policy);
      expect(r4.allowed).toBe(false);
    });

    it('should cap application allowlist by organization policy ceiling', () => {
      const policy = {
        appKey: 'my-app',
        appAllowlist: [
          { host: 'api.slack.com', ports: [443] },
          { host: 'api.external.com', ports: [443] },
        ],
        // Org only allows slack
        orgCeiling: [{ host: 'api.slack.com', ports: [443] }],
      };

      // In app allowlist AND in org ceiling -> ALLOWED
      const r1 = evaluateEgressPolicy('api.slack.com', 443, policy);
      expect(r1.allowed).toBe(true);

      // In app allowlist BUT NOT in org ceiling -> DENIED (app cannot widen ceiling)
      const r2 = evaluateEgressPolicy('api.external.com', 443, policy);
      expect(r2.allowed).toBe(false);
      expect(r2.reason).toContain('exceeds organization policy ceiling');
    });
  });

  describe('3. Egress Proxy HTTP & CONNECT Enforcement', () => {
    it('should block undeclared outbound HTTP request with 403 EGRESS_DENIED', async () => {
      // Register app with no egress
      policyManager.registerAppPolicy('no-egress-app', []);

      const reqOptions: http.RequestOptions = {
        hostname: '127.0.0.1',
        port: PROXY_PORT,
        path: 'http://api.example.com/data',
        method: 'GET',
        headers: {
          'x-capsule-key': 'no-egress-app',
          Host: 'api.example.com',
        },
      };

      const response = await new Promise<{ statusCode: number; body: string }>((resolve, reject) => {
        const req = http.request(reqOptions, (res) => {
          let data = '';
          res.on('data', (c) => (data += c));
          res.on('end', () => resolve({ statusCode: res.statusCode || 0, body: data }));
        });
        req.on('error', reject);
        req.end();
      });

      expect(response.statusCode).toBe(403);
      const parsed = JSON.parse(response.body);
      expect(parsed.error).toBe('EGRESS_DENIED');

      // Verify audit log
      const events = logger.getEvents({ appKey: 'no-egress-app', decision: 'denied' });
      expect(events.length).toBeGreaterThan(0);
      expect(events[0].host).toBe('api.example.com');
      expect(events[0].decision).toBe('denied');
    });

    it('should block SSRF and private destinations with 403 SSRF_BLOCKED', async () => {
      // App allows rebinding.bad.com, but rebinding resolves to 127.0.0.1
      policyManager.registerAppPolicy('app-with-bad-domain', ['rebinding.bad.com']);

      const reqOptions: http.RequestOptions = {
        hostname: '127.0.0.1',
        port: PROXY_PORT,
        path: 'http://rebinding.bad.com/secret',
        method: 'GET',
        headers: {
          'x-capsule-key': 'app-with-bad-domain',
          Host: 'rebinding.bad.com',
        },
      };

      const response = await new Promise<{ statusCode: number; body: string }>((resolve, reject) => {
        const req = http.request(reqOptions, (res) => {
          let data = '';
          res.on('data', (c) => (data += c));
          res.on('end', () => resolve({ statusCode: res.statusCode || 0, body: data }));
        });
        req.on('error', reject);
        req.end();
      });

      expect(response.statusCode).toBe(403);
      const parsed = JSON.parse(response.body);
      expect(parsed.error).toBe('SSRF_BLOCKED');
      expect(parsed.message).toContain('Loopback address');

      // Verify audit event
      const events = logger.getEvents({ appKey: 'app-with-bad-domain', decision: 'denied' });
      expect(events.length).toBeGreaterThan(0);
      expect(events[0].destinationIp).toBe('127.0.0.1');
    });

    it('should block HTTPS CONNECT tunneling for unauthorized destinations', async () => {
      policyManager.registerAppPolicy('connect-test-app', ['safe.example.com']);

      const socket = net.connect(PROXY_PORT, '127.0.0.1', () => {
        socket.write(
          'CONNECT unauthorized.com:443 HTTP/1.1\r\n' +
            'Host: unauthorized.com:443\r\n' +
            'x-capsule-key: connect-test-app\r\n\r\n'
        );
      });

      const responseData = await new Promise<string>((resolve) => {
        socket.on('data', (d) => {
          resolve(d.toString());
          socket.end();
        });
      });

      expect(responseData).toContain('403 Forbidden');
      expect(responseData).toContain('EGRESS_DENIED');

      const events = logger.getEvents({ appKey: 'connect-test-app', decision: 'denied' });
      expect(events.length).toBeGreaterThan(0);
      expect(events[0].host).toBe('unauthorized.com');
    });
  });
});
