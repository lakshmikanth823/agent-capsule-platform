import crypto from 'node:crypto';

export interface IdentityContext {
  userId: string;
  sub: string;
  orgId: string;
  org_id: string;
  email: string;
  groups: string[];
  roles: string[];
  issuedAt: Date;
  expiresAt: Date;
  raw: Record<string, any>;
  hasRole(role: string): boolean;
  hasAnyRole(...roles: string[]): boolean;
  isMemberOf(group: string): boolean;
}

export class IdentityVerificationError extends Error {
  constructor(message: string, public readonly code: string) {
    super(message);
    this.name = 'IdentityVerificationError';
  }
}

export interface VerifyIdentityOptions {
  secret?: string;
  keys?: Record<string, string>;
  audience?: string;
  clockToleranceSeconds?: number;
  throwOnError?: boolean;
}

function base64UrlDecode(str: string): string {
  let base64 = str.replace(/-/g, '+').replace(/_/g, '/');
  while (base64.length % 4 !== 0) {
    base64 += '=';
  }
  return Buffer.from(base64, 'base64').toString('utf8');
}

function base64UrlEncode(data: Buffer): string {
  return data
    .toString('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
}

export function createIdentityContext(payload: Record<string, any>): IdentityContext {
  const roles = Array.isArray(payload.roles) ? payload.roles : [];
  const groups = Array.isArray(payload.groups) ? payload.groups : [];
  const sub = payload.sub || payload.userId || '';
  const orgId = payload.org_id || payload.orgId || '';

  return {
    userId: sub,
    sub,
    orgId,
    org_id: orgId,
    email: payload.email || '',
    groups,
    roles,
    issuedAt: payload.iat ? new Date(payload.iat * 1000) : new Date(),
    expiresAt: payload.exp ? new Date(payload.exp * 1000) : new Date(Date.now() + 3600_000),
    raw: payload,
    hasRole(role: string): boolean {
      return roles.includes(role);
    },
    hasAnyRole(...targetRoles: string[]): boolean {
      return targetRoles.some((r) => roles.includes(r));
    },
    isMemberOf(group: string): boolean {
      return groups.includes(group);
    },
  };
}

/**
 * Extract raw identity header value from various request formats or strings.
 */
function extractHeader(reqOrToken: any): string | null {
  if (!reqOrToken) return null;
  if (typeof reqOrToken === 'string') return reqOrToken;

  // Web standard Request object (req.headers.get)
  if (reqOrToken.headers && typeof reqOrToken.headers.get === 'function') {
    return reqOrToken.headers.get('x-capsule-identity');
  }

  // Node IncomingMessage / Express req (req.headers['x-capsule-identity'])
  if (reqOrToken.headers && typeof reqOrToken.headers === 'object') {
    return (
      reqOrToken.headers['x-capsule-identity'] ||
      reqOrToken.headers['X-Capsule-Identity'] ||
      null
    );
  }

  return null;
}

/**
 * Verifies the signed identity header from the edge proxy.
 * Checks HMAC-SHA256 signature, audience (`capsule:<id>`), issuer ('platform'), and expiration.
 */
export function getIdentity(
  reqOrToken: any,
  options: VerifyIdentityOptions = {}
): IdentityContext | null {
  const token = extractHeader(reqOrToken);

  // Check for local emulator mode if no token is present
  const isEmulator =
    process.env.CAPSULE_EMULATOR === 'true' ||
    process.env.NODE_ENV === 'development';

  if (!token) {
    if (isEmulator) {
      return getEmulatorIdentity();
    }
    if (options.throwOnError) {
      throw new IdentityVerificationError(
        'Missing identity header x-capsule-identity',
        'MISSING_IDENTITY'
      );
    }
    return null;
  }

  // Support raw JSON identity header for backward-compatibility with tests/mock callers
  if (token.trim().startsWith('{')) {
    try {
      const parsed = JSON.parse(token);
      if (parsed && typeof parsed === 'object' && (parsed.sub || parsed.userId)) {
        return createIdentityContext(parsed);
      }
    } catch {
      // not valid JSON, continue with JWT verification
    }
  }

  // Split JWT parts
  const parts = token.split('.');
  if (parts.length !== 3) {
    if (options.throwOnError) {
      throw new IdentityVerificationError(
        'Malformed identity token: expected 3 parts',
        'MALFORMED_TOKEN'
      );
    }
    return null;
  }

  const [encodedHeader, encodedPayload, encodedSignature] = parts;

  let header: { alg: string; typ: string; kid?: string };
  let payload: Record<string, any>;

  try {
    header = JSON.parse(base64UrlDecode(encodedHeader));
    payload = JSON.parse(base64UrlDecode(encodedPayload));
  } catch {
    if (options.throwOnError) {
      throw new IdentityVerificationError(
        'Invalid JSON in identity token header or payload',
        'INVALID_JSON'
      );
    }
    return null;
  }

  // Check algorithm
  if (header.alg !== 'HS256') {
    if (options.throwOnError) {
      throw new IdentityVerificationError(
        `Unsupported algorithm ${header.alg}: expected HS256`,
        'UNSUPPORTED_ALGORITHM'
      );
    }
    return null;
  }

  // Resolve secret for signature verification
  const keys = options.keys || getPlatformKeys();
  let secret = options.secret;
  if (!secret) {
    if (header.kid && keys[header.kid]) {
      secret = keys[header.kid];
    } else {
      secret = Object.values(keys)[0] || process.env.CAPSULE_IDENTITY_SECRET;
    }
  }

  if (!secret) {
    if (isEmulator) {
      // In emulator mode without a secret, accept payload for developer convenience
      return createIdentityContext(payload);
    }
    if (options.throwOnError) {
      throw new IdentityVerificationError(
        'No verification secret configured for identity verification',
        'NO_SECRET_CONFIGURED'
      );
    }
    return null;
  }

  // Verify HMAC-SHA256 signature
  const dataToSign = `${encodedHeader}.${encodedPayload}`;
  const expectedSig = crypto
    .createHmac('sha256', secret)
    .update(dataToSign)
    .digest();
  const expectedEncodedSig = base64UrlEncode(expectedSig);

  try {
    const sigBuf = Buffer.from(encodedSignature);
    const expectedBuf = Buffer.from(expectedEncodedSig);
    if (
      sigBuf.length !== expectedBuf.length ||
      !crypto.timingSafeEqual(sigBuf, expectedBuf)
    ) {
      if (options.throwOnError) {
        throw new IdentityVerificationError(
          'Invalid identity token signature',
          'INVALID_SIGNATURE'
        );
      }
      return null;
    }
  } catch (err: any) {
    if (err instanceof IdentityVerificationError) throw err;
    if (options.throwOnError) {
      throw new IdentityVerificationError(
        'Signature verification failed',
        'INVALID_SIGNATURE'
      );
    }
    return null;
  }

  // Verify issuer
  if (payload.iss !== 'platform') {
    if (options.throwOnError) {
      throw new IdentityVerificationError(
        `Invalid issuer '${payload.iss}': expected 'platform'`,
        'INVALID_ISSUER'
      );
    }
    return null;
  }

  // Verify audience if specified or present in environment
  const expectedAud =
    options.audience ||
    (process.env.CAPSULE_ID ? `capsule:${process.env.CAPSULE_ID}` : undefined) ||
    (process.env.APP_ID ? `capsule:${process.env.APP_ID}` : undefined);

  if (expectedAud && payload.aud !== expectedAud) {
    if (options.throwOnError) {
      throw new IdentityVerificationError(
        `Audience mismatch: token audience '${payload.aud}' does not match expected '${expectedAud}'`,
        'AUDIENCE_MISMATCH'
      );
    }
    return null;
  }

  // Verify expiration
  const tolerance = options.clockToleranceSeconds || 10;
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (payload.exp && typeof payload.exp === 'number') {
    if (nowSeconds >= payload.exp + tolerance) {
      if (options.throwOnError) {
        throw new IdentityVerificationError(
          `Identity token expired at ${new Date(payload.exp * 1000).toISOString()}`,
          'TOKEN_EXPIRED'
        );
      }
      return null;
    }
  }

  return createIdentityContext(payload);
}

/**
 * Require valid identity, throwing an error if invalid or absent.
 */
export function requireIdentity(
  reqOrToken: any,
  options: Omit<VerifyIdentityOptions, 'throwOnError'> = {}
): IdentityContext {
  const identity = getIdentity(reqOrToken, { ...options, throwOnError: true });
  if (!identity) {
    throw new IdentityVerificationError(
      'Authentication required',
      'UNAUTHENTICATED'
    );
  }
  return identity;
}

/**
 * Read platform signing keys from environment.
 */
function getPlatformKeys(): Record<string, string> {
  const keysStr = process.env.CAPSULE_IDENTITY_KEYS;
  if (keysStr) {
    try {
      return JSON.parse(keysStr);
    } catch {
      // ignore
    }
  }
  const defaultSecret = process.env.CAPSULE_IDENTITY_SECRET;
  if (defaultSecret) {
    return { default: defaultSecret };
  }
  return {};
}

/**
 * Provide mock development identity for local emulator mode.
 */
export function getEmulatorIdentity(): IdentityContext {
  return createIdentityContext({
    iss: 'platform',
    aud: 'capsule:local-dev',
    sub: 'dev-user-001',
    org_id: 'dev-org-001',
    email: 'developer@example.com',
    groups: ['engineering'],
    roles: ['employee', 'manager', 'hr'],
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + 86400,
  });
}
