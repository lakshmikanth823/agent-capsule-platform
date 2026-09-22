/**
 * Egress Proxy Server
 *
 * Implements TRD Section 20 and PRD FR-019 / FR-020 / FR-021 / FR-022:
 * - Default deny for all outbound traffic.
 * - Per-app allowlist from manifest, capped by org policy ceiling.
 * - Connection-time SSRF and DNS rebinding protection (pins connection to validated IP).
 * - Comprehensive network audit logging for every allowed and denied attempt.
 * - Supports both HTTP proxying and HTTPS CONNECT tunneling.
 */
import http from 'node:http';
import net from 'node:net';
import { URL } from 'node:url';
import { resolveAndValidateDestination } from './ssrf.js';
import { evaluateEgressPolicy, EgressPolicy, EgressRule } from './policy.js';
import { EgressLogger } from './logger.js';

export * from './ssrf.js';
export * from './policy.js';
export * from './logger.js';

export interface EgressProxyConfig {
  port?: number;
  host?: string;
  defaultOrgCeiling?: EgressRule[];
}

export class EgressPolicyManager {
  private appPolicies = new Map<string, EgressPolicy & { orgId?: string }>();
  private orgCeilings = new Map<string, EgressRule[]>(); // orgId -> EgressRule[]
  private frozenOrgs = new Set<string>();
  private suspendedApps = new Set<string>();
  private egressUsage = new Map<string, { bytes: number; resetAt: number }>();
  private appByteLimits = new Map<string, number>();
  public defaultDailyByteLimit = 100 * 1024 * 1024; // 100 MB default

  registerAppPolicy(appKey: string, allowlist: (EgressRule | string)[], orgId?: string): void {
    const normalizedRules: EgressRule[] = allowlist.map((r) =>
      typeof r === 'string' ? { host: r } : r
    );

    const orgCeiling = orgId ? this.orgCeilings.get(orgId) : undefined;

    this.appPolicies.set(appKey, {
      appKey,
      appAllowlist: normalizedRules,
      orgCeiling,
      orgId,
    });
  }

  setPolicy(appKey: string, policy: { appKey?: string; appAllowlist: (EgressRule | string)[]; orgCeiling?: EgressRule[]; orgId?: string; dailyByteLimit?: number }): void {
    this.registerAppPolicy(appKey, policy.appAllowlist, policy.orgId);
    if (policy.dailyByteLimit) {
      this.appByteLimits.set(appKey, policy.dailyByteLimit);
    }
  }

  setOrgCeiling(orgId: string, ceiling: (EgressRule | string)[]): void {

    const normalizedCeiling: EgressRule[] = ceiling.map((r) =>
      typeof r === 'string' ? { host: r } : r
    );
    this.orgCeilings.set(orgId, normalizedCeiling);

    // Update any existing app policies for this org
    for (const [, policy] of this.appPolicies.entries()) {
      if (policy.orgId === orgId) {
        policy.orgCeiling = normalizedCeiling;
      }
    }
  }

  freezeOrg(orgId: string): void {
    this.frozenOrgs.add(orgId);
  }

  resumeOrg(orgId: string): void {
    this.frozenOrgs.delete(orgId);
  }

  isOrgFrozen(orgId: string): boolean {
    return this.frozenOrgs.has(orgId);
  }

  suspendApp(appKey: string): void {
    this.suspendedApps.add(appKey);
  }

  resumeApp(appKey: string): void {
    this.suspendedApps.delete(appKey);
  }

  isAppSuspended(appKey: string): boolean {
    if (this.suspendedApps.has(appKey)) return true;
    const policy = this.appPolicies.get(appKey);
    if (policy && policy.orgId && this.frozenOrgs.has(policy.orgId)) return true;
    return false;
  }


  checkAndTrackEgress(appKey: string, bytes: number, limitBytes?: number): { allowed: boolean; currentBytes: number; limitBytes: number } {
    const limit = limitBytes || this.appByteLimits.get(appKey) || this.defaultDailyByteLimit;
    const now = Date.now();
    const usage = this.egressUsage.get(appKey) || { bytes: 0, resetAt: now + 86400000 };

    // Reset daily counter if expired
    if (now > usage.resetAt) {
      usage.bytes = 0;
      usage.resetAt = now + 86400000;
    }

    if (usage.bytes + bytes > limit) {
      return { allowed: false, currentBytes: usage.bytes, limitBytes: limit };
    }

    usage.bytes += bytes;
    this.egressUsage.set(appKey, usage);
    return { allowed: true, currentBytes: usage.bytes, limitBytes: limit };
  }

  getPolicy(appKey: string): (EgressPolicy & { orgId?: string }) | undefined {
    return this.appPolicies.get(appKey);
  }

  clear(): void {
    this.appPolicies.clear();
    this.orgCeilings.clear();
    this.frozenOrgs.clear();
    this.suspendedApps.clear();
    this.egressUsage.clear();
    this.appByteLimits.clear();
  }
}


export function createEgressProxyServer(options: {
  config?: EgressProxyConfig;
  policyManager?: EgressPolicyManager;
  logger?: EgressLogger;
  dnsResolver?: any;
}) {
  const policyManager = options.policyManager || new EgressPolicyManager();
  const logger = options.logger || new EgressLogger();
  const dnsResolver = options.dnsResolver;

  function extractAppKey(req: http.IncomingMessage): string {
    // 1. Check custom headers
    const appKeyHeader =
      req.headers['x-capsule-key'] ||
      req.headers['x-capsule-id'] ||
      req.headers['x-capsule-app-key'];
    if (appKeyHeader && typeof appKeyHeader === 'string') {
      return appKeyHeader;
    }

    // 2. Check Proxy-Authorization header (e.g. Basic base64(appKey:token))
    const proxyAuth = req.headers['proxy-authorization'];
    if (proxyAuth && proxyAuth.startsWith('Basic ')) {
      try {
        const decoded = Buffer.from(proxyAuth.substring(6), 'base64').toString('utf-8');
        const [appKey] = decoded.split(':');
        if (appKey) return appKey;
      } catch {
        // ignore
      }
    }

    return 'unknown-app';
  }

  const server = http.createServer(async (req, res) => {
    const appKey = extractAppKey(req);
    const method = req.method || 'GET';

    let targetUrl: URL;
    try {
      targetUrl = new URL(req.url || '/');
    } catch {
      // If relative path, try using Host header
      const host = req.headers.host || 'unknown';
      try {
        targetUrl = new URL(`http://${host}${req.url}`);
      } catch {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'BAD_REQUEST', message: 'Malformed target URL' }));
        return;
      }
    }

    const targetHost = targetUrl.hostname;
    const targetPort = targetUrl.port
      ? parseInt(targetUrl.port, 10)
      : targetUrl.protocol === 'https:'
      ? 443
      : 80;

    // 0. Kill Switch & Suspension Check
    const orgId =
      (req.headers['x-capsule-org-id'] as string) ||
      policyManager.getPolicy(appKey)?.orgId;
    if (orgId && policyManager.isOrgFrozen(orgId)) {
      logger.logEvent({
        appKey,
        method,
        host: targetHost,
        port: targetPort,
        decision: 'denied',
        reason: 'Organization is frozen',
      });
      res.writeHead(403, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          error: 'ORGANIZATION_FROZEN',
          code: 'ORGANIZATION_FROZEN',
          message: `Egress is blocked because organization '${orgId}' is frozen.`,
        })
      );
      return;
    }

    if (policyManager.isAppSuspended(appKey)) {
      logger.logEvent({
        appKey,
        method,
        host: targetHost,
        port: targetPort,
        decision: 'denied',
        reason: 'Capsule is suspended',
      });
      res.writeHead(403, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          error: 'APP_SUSPENDED',
          code: 'APP_SUSPENDED',
          message: `Egress is blocked because capsule '${appKey}' is suspended.`,
        })
      );
      return;
    }


    // 0.1 Daily Egress Quota Check
    const estimatedBytes = (req.headers['content-length'] ? parseInt(req.headers['content-length'] as string, 10) : 0) + 1024;
    const quotaCheck = policyManager.checkAndTrackEgress(appKey, estimatedBytes);
    if (!quotaCheck.allowed) {
      logger.logEvent({
        appKey,
        method,
        host: targetHost,
        port: targetPort,
        decision: 'denied',
        reason: 'Daily egress byte quota exceeded',
      });
      res.writeHead(403, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          error: 'QUOTA_EXCEEDED',
          code: 'QUOTA_EXCEEDED',
          metric: 'egress_bytes_per_day',
          limit_bytes: quotaCheck.limitBytes,
          current_bytes: quotaCheck.currentBytes,
          message: `Daily egress quota of ${Math.round(quotaCheck.limitBytes / (1024 * 1024))}MB exceeded for capsule '${appKey}'.`,
        })
      );
      return;
    }

    // 1. Policy Evaluation
    const policy = policyManager.getPolicy(appKey) || {
      appKey,
      appAllowlist: [],
      orgCeiling: options.config?.defaultOrgCeiling,
    };

    const evaluation = evaluateEgressPolicy(targetHost, targetPort, policy);
    if (!evaluation.allowed) {
      logger.logEvent({
        appKey,
        method,
        host: targetHost,
        port: targetPort,
        decision: 'denied',
        reason: evaluation.reason,
      });

      res.writeHead(403, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          error: 'EGRESS_DENIED',
          code: 'EGRESS_DENIED',
          message: evaluation.reason,
          destination: `${targetHost}:${targetPort}`,
        })
      );
      return;
    }

    // 2. Connection-time SSRF & DNS Rebinding Check
    const ssrfCheck = await resolveAndValidateDestination(targetHost, dnsResolver);
    if (!ssrfCheck.valid || !ssrfCheck.ip) {
      logger.logEvent({
        appKey,
        method,
        host: targetHost,
        port: targetPort,
        destinationIp: ssrfCheck.ip,
        decision: 'denied',
        reason: ssrfCheck.reason || 'SSRF blocked',
      });

      res.writeHead(403, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          error: 'SSRF_BLOCKED',
          code: 'SSRF_BLOCKED',
          message: ssrfCheck.reason,
          destination: `${targetHost}:${targetPort}`,
        })
      );
      return;
    }

    // 3. Connect to validated IP (pinning IP prevents DNS rebinding)
    logger.logEvent({
      appKey,
      method,
      host: targetHost,
      port: targetPort,
      destinationIp: ssrfCheck.ip,
      decision: 'allowed',
      reason: evaluation.reason,
    });

    const proxyReq = http.request(
      {
        host: ssrfCheck.ip, // Connect directly to validated IP
        port: targetPort,
        path: targetUrl.pathname + targetUrl.search,
        method,
        headers: {
          ...req.headers,
          host: req.headers.host || targetHost, // Preserve original Host header
        },
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode || 200, proxyRes.headers);
        proxyRes.pipe(res);
      }
    );

    proxyReq.on('error', (err) => {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'BAD_GATEWAY', message: err.message }));
    });

    req.pipe(proxyReq);
  });

  // Handle HTTPS CONNECT Tunneling
  server.on('connect', async (req, clientSocket, head) => {
    const appKey = extractAppKey(req);
    const method = 'CONNECT';

    const [targetHost, portStr] = (req.url || '').split(':');
    const targetPort = portStr ? parseInt(portStr, 10) : 443;

    if (!targetHost) {
      clientSocket.write('HTTP/1.1 400 Bad Request\r\n\r\n');
      clientSocket.end();
      return;
    }

    // 0. Kill Switch & Suspension Check
    const orgId =
      (req.headers['x-capsule-org-id'] as string) ||
      policyManager.getPolicy(appKey)?.orgId;
    if (orgId && policyManager.isOrgFrozen(orgId)) {
      logger.logEvent({
        appKey,
        method,
        host: targetHost,
        port: targetPort,
        decision: 'denied',
        reason: 'Organization is frozen',
      });
      clientSocket.write(
        'HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\n\r\n{"error":"ORGANIZATION_FROZEN","code":"ORGANIZATION_FROZEN","message":"Egress blocked because organization is frozen."}'
      );
      clientSocket.end();
      return;
    }

    if (policyManager.isAppSuspended(appKey)) {
      logger.logEvent({
        appKey,
        method,
        host: targetHost,
        port: targetPort,
        decision: 'denied',
        reason: 'Capsule is suspended',
      });
      clientSocket.write(
        'HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\n\r\n{"error":"APP_SUSPENDED","code":"APP_SUSPENDED","message":"Egress blocked because capsule is suspended."}'
      );
      clientSocket.end();
      return;
    }


    // 0.1 Daily Quota Check
    const quotaCheck = policyManager.checkAndTrackEgress(appKey, 4096);
    if (!quotaCheck.allowed) {
      logger.logEvent({
        appKey,
        method,
        host: targetHost,
        port: targetPort,
        decision: 'denied',
        reason: 'Daily egress byte quota exceeded',
      });
      clientSocket.write(
        `HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\n\r\n{"error":"QUOTA_EXCEEDED","code":"QUOTA_EXCEEDED","metric":"egress_bytes_per_day","limit_bytes":${quotaCheck.limitBytes},"current_bytes":${quotaCheck.currentBytes}}`
      );
      clientSocket.end();
      return;
    }

    // 1. Policy Evaluation
    const policy = policyManager.getPolicy(appKey) || {
      appKey,
      appAllowlist: [],
      orgCeiling: options.config?.defaultOrgCeiling,
    };

    const evaluation = evaluateEgressPolicy(targetHost, targetPort, policy);
    if (!evaluation.allowed) {
      logger.logEvent({
        appKey,
        method,
        host: targetHost,
        port: targetPort,
        decision: 'denied',
        reason: evaluation.reason,
      });

      clientSocket.write(
        `HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\n\r\n{"error":"EGRESS_DENIED","message":"${evaluation.reason}"}`
      );
      clientSocket.end();
      return;
    }

    // 2. SSRF & DNS Rebinding Check at connection time
    const ssrfCheck = await resolveAndValidateDestination(targetHost, dnsResolver);
    if (!ssrfCheck.valid || !ssrfCheck.ip) {
      logger.logEvent({
        appKey,
        method,
        host: targetHost,
        port: targetPort,
        destinationIp: ssrfCheck.ip,
        decision: 'denied',
        reason: ssrfCheck.reason || 'SSRF blocked',
      });

      clientSocket.write(
        `HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\n\r\n{"error":"SSRF_BLOCKED","message":"${ssrfCheck.reason}"}`
      );
      clientSocket.end();
      return;
    }

    // 3. Connect to validated IP (pinning IP)
    logger.logEvent({
      appKey,
      method,
      host: targetHost,
      port: targetPort,
      destinationIp: ssrfCheck.ip,
      decision: 'allowed',
      reason: evaluation.reason,
    });

    const targetSocket = net.connect(targetPort, ssrfCheck.ip, () => {
      clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head && head.length > 0) {
        targetSocket.write(head);
      }
      targetSocket.pipe(clientSocket);
      clientSocket.pipe(targetSocket);
    });

    targetSocket.on('error', () => {
      clientSocket.write('HTTP/1.1 502 Bad Gateway\r\n\r\n');
      clientSocket.end();
    });

    clientSocket.on('error', () => {
      targetSocket.end();
    });
  });

  return server;
}
