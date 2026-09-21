/**
 * Egress Policy Engine
 *
 * Implements TRD Section 20 and PRD FR-019 / FR-020:
 * - Default deny.
 * - Per-app allowlist from manifest.
 * - Capped by organization policy ceiling (app can narrow it, never widen it).
 */

export interface EgressRule {
  host: string;
  ports?: number[];
}

export interface EgressPolicy {
  appKey: string;
  appAllowlist: EgressRule[];
  orgCeiling?: EgressRule[]; // undefined means org has no restrictive ceiling
}

export interface PolicyEvaluation {
  allowed: boolean;
  reason: string;
  matchedRule?: EgressRule;
}

/**
 * Checks if a target host matches a policy pattern.
 * Supports exact matches ("api.example.com") and wildcard prefixes ("*.example.com").
 */
export function matchesHostPattern(targetHost: string, pattern: string): boolean {
  const cleanTarget = targetHost.toLowerCase().trim();
  const cleanPattern = pattern.toLowerCase().trim();

  if (cleanPattern === cleanTarget) {
    return true;
  }

  if (cleanPattern.startsWith('*.')) {
    const rootDomain = cleanPattern.slice(2);
    // Matches subdomain (e.g. "sub.example.com" matches "*.example.com")
    if (cleanTarget.endsWith('.' + rootDomain)) {
      return true;
    }
  }

  return false;
}

/**
 * Checks if a target port matches allowed ports for a rule.
 * Defaults to standard web ports [80, 443] if ports list is omitted.
 */
export function matchesPort(targetPort: number, allowedPorts?: number[]): boolean {
  if (!allowedPorts || allowedPorts.length === 0) {
    return targetPort === 80 || targetPort === 443;
  }
  return allowedPorts.includes(targetPort);
}

/**
 * Evaluates whether a destination (host + port) is permitted under an allowlist.
 */
export function isAllowedByRules(
  targetHost: string,
  targetPort: number,
  rules: EgressRule[]
): { allowed: boolean; rule?: EgressRule } {
  for (const rule of rules) {
    if (matchesHostPattern(targetHost, rule.host) && matchesPort(targetPort, rule.ports)) {
      return { allowed: true, rule };
    }
  }
  return { allowed: false };
}

/**
 * Evaluates full policy:
 * 1. Must be allowed by app allowlist (Default deny if app has no rules).
 * 2. If organization ceiling is present, must ALSO be allowed by org ceiling.
 *
 * Effective = AppRules ∩ OrgCeiling
 */
export function evaluateEgressPolicy(
  targetHost: string,
  targetPort: number,
  policy: EgressPolicy
): PolicyEvaluation {
  // 1. Default Deny: App must explicitly allow the destination
  if (!policy.appAllowlist || policy.appAllowlist.length === 0) {
    return {
      allowed: false,
      reason: `Default deny: capsule '${policy.appKey}' declared no egress allowlist in manifest.`,
    };
  }

  const appCheck = isAllowedByRules(targetHost, targetPort, policy.appAllowlist);
  if (!appCheck.allowed) {
    return {
      allowed: false,
      reason: `Destination ${targetHost}:${targetPort} is not in capsule '${policy.appKey}' allowlist.`,
    };
  }

  // 2. Organization Ceiling Check: App can narrow org policy, but never widen it
  if (policy.orgCeiling !== undefined) {
    const orgCheck = isAllowedByRules(targetHost, targetPort, policy.orgCeiling);
    if (!orgCheck.allowed) {
      return {
        allowed: false,
        reason: `Destination ${targetHost}:${targetPort} exceeds organization policy ceiling.`,
      };
    }
  }

  return {
    allowed: true,
    reason: `Allowed by capsule allowlist rule '${appCheck.rule?.host}'`,
    matchedRule: appCheck.rule,
  };
}
