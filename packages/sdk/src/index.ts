/**
 * @capsule/sdk
 * Platform SDK for the blessed Node.js 22 + TypeScript application shape.
 * Note: The platform, not this SDK, is the security boundary.
 */

export interface IdentityContext {
  iss: string;
  aud: string;
  sub: string;
  org_id: string;
  groups: string[];
  roles: string[];
  iat: number;
  exp: number;
}

export function parseIdentityHeader(headerValue?: string): IdentityContext | null {
  if (!headerValue) return null;
  try {
    const parsed = JSON.parse(headerValue);
    if (parsed && typeof parsed.sub === 'string') {
      return parsed as IdentityContext;
    }
    return null;
  } catch {
    return null;
  }
}

export const sdkVersion = '0.1.0';
