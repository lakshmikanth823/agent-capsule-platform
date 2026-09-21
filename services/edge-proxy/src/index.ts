/**
 * @capsule/edge-proxy
 * Edge reverse proxy providing per-Capsule origin isolation,
 * OIDC token verification, and signed identity context injection.
 */

export interface EdgeRouteConfig {
  capsuleId: string;
  targetPort: number;
  hostHeader: string;
}

export function extractSubdomainCapsuleId(hostname: string, baseDomain = 'localhost'): string | null {
  const parts = hostname.split(':')[0].split('.');
  if (parts.length > 1 && parts[parts.length - 1] === baseDomain) {
    return parts[0];
  }
  return null;
}
