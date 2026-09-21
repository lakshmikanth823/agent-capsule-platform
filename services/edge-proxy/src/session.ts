/**
 * Per-App Session Management
 *
 * Implements RFC 6265 Host-Only Cookies:
 * By omitting the `Domain` attribute in `Set-Cookie`, the browser strictly associates
 * the cookie with the exact request hostname (e.g. `leave-tracker.apps.localhost`).
 * The cookie is NEVER sent to other subdomains (e.g. `calc.apps.localhost`) or to the
 * parent domain / dashboard.
 */
import { signJwt, verifyJwt } from './crypto.js';

export const SESSION_COOKIE_NAME = 'capsule_session';

export interface AppSession {
  sub: string;
  email: string;
  org_id: string;
  app_key: string;
  platform_role: string;
  app_roles: string[];
  groups?: string[];
  iat: number;
  exp: number;
}

export function createSessionToken(session: Omit<AppSession, 'iat' | 'exp'>, secret: string, durationSeconds = 43200): string {
  const now = Math.floor(Date.now() / 1000);
  const payload: AppSession = {
    ...session,
    iat: now,
    exp: now + durationSeconds,
  };
  return signJwt(payload, secret);
}

export function verifySessionToken(token: string, secret: string): AppSession | null {
  const verified = verifyJwt<AppSession>(token, { default: secret });
  return verified ? verified.payload : null;
}

/**
 * Format a Set-Cookie header string that is strictly host-only.
 * Note: Omission of `Domain=` makes this host-only per RFC 6265 Section 4.1.2.3.
 */
export function createHostOnlyCookie(
  sessionToken: string,
  isProduction = false,
  maxAgeSeconds = 43200
): string {
  let cookie = `${SESSION_COOKIE_NAME}=${sessionToken}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAgeSeconds}`;
  if (isProduction) {
    cookie += '; Secure';
  }
  return cookie;
}

export function createClearCookie(isProduction = false): string {
  let cookie = `${SESSION_COOKIE_NAME}=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax; Max-Age=0`;
  if (isProduction) {
    cookie += '; Secure';
  }
  return cookie;
}

export function parseCookies(cookieHeader?: string): Record<string, string> {
  if (!cookieHeader) return {};
  const cookies: Record<string, string> = {};
  const pairs = cookieHeader.split(';');
  for (const pair of pairs) {
    const idx = pair.indexOf('=');
    if (idx > 0) {
      const key = pair.slice(0, idx).trim();
      const val = pair.slice(idx + 1).trim();
      cookies[key] = val;
    }
  }
  return cookies;
}

export function getSessionFromRequest(
  cookieHeader: string | undefined,
  expectedAppKey: string,
  secret: string
): AppSession | null {
  const cookies = parseCookies(cookieHeader);
  const token = cookies[SESSION_COOKIE_NAME];
  if (!token) return null;

  const session = verifySessionToken(token, secret);
  if (!session) return null;

  // Strict check: session must belong to the exact app requested
  if (session.app_key !== expectedAppKey) {
    return null;
  }

  return session;
}
