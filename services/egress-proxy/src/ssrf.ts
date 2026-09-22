/**
 * SSRF and DNS Rebinding Prevention Module
 *
 * Implements TRD Section 20 and PRD FR-021:
 * - Blocks internal IPs, RFC 1918 private ranges, loopback, link-local, cloud metadata.
 * - Handles IPv6 equivalents (ULA, link-local, IPv4-mapped IPv6).
 * - Performs connection-time IP validation to eliminate DNS-rebinding attacks.
 */
import dns from "node:dns/promises";
import net from "node:net";

export interface IpValidationResult {
  valid: boolean;
  ip?: string;
  reason?: string;
}

/**
 * Checks if an IPv4 address (in integer form) falls within a CIDR range.
 */
function ip4ToInt(ip: string): number {
  return ip
    .split(".")
    .reduce((acc, octet) => ((acc << 8) + parseInt(octet, 10)) >>> 0, 0);
}

function isIp4InCidr(
  ipInt: number,
  cidrBase: string,
  prefixLen: number,
): boolean {
  const baseInt = ip4ToInt(cidrBase);
  const mask = prefixLen === 0 ? 0 : (~0 << (32 - prefixLen)) >>> 0;
  return (ipInt & mask) === (baseInt & mask);
}

/**
 * Check if an IPv4 address is in a blocked/private range.
 */
export function isPrivateOrBlockedIp4(ip: string): {
  blocked: boolean;
  reason?: string;
} {
  if (!net.isIPv4(ip)) return { blocked: true, reason: "Invalid IPv4 address" };

  const ipInt = ip4ToInt(ip);

  // 0.0.0.0/8 (Current network)
  if (isIp4InCidr(ipInt, "0.0.0.0", 8)) {
    return { blocked: true, reason: "Current network (0.0.0.0/8) is blocked" };
  }
  // 10.0.0.0/8 (RFC 1918 Private)
  if (isIp4InCidr(ipInt, "10.0.0.0", 8)) {
    return { blocked: true, reason: "Private network (10.0.0.0/8) is blocked" };
  }
  // 100.64.0.0/10 (Carrier-Grade NAT)
  if (isIp4InCidr(ipInt, "100.64.0.0", 10)) {
    return {
      blocked: true,
      reason: "Carrier-grade NAT (100.64.0.0/10) is blocked",
    };
  }
  // 127.0.0.0/8 (Loopback)
  if (isIp4InCidr(ipInt, "127.0.0.0", 8)) {
    return {
      blocked: true,
      reason: "Loopback address (127.0.0.0/8) is blocked",
    };
  }
  // 169.254.0.0/16 (Link-local / APIPA / Cloud Metadata 169.254.169.254)
  if (isIp4InCidr(ipInt, "169.254.0.0", 16)) {
    return {
      blocked: true,
      reason: "Link-local / Cloud Metadata (169.254.0.0/16) is blocked",
    };
  }
  // 172.16.0.0/12 (RFC 1918 Private)
  if (isIp4InCidr(ipInt, "172.16.0.0", 12)) {
    return {
      blocked: true,
      reason: "Private network (172.16.0.0/12) is blocked",
    };
  }
  // 192.0.0.0/24 (IETF Protocol Assignments)
  if (isIp4InCidr(ipInt, "192.0.0.0", 24)) {
    return {
      blocked: true,
      reason: "IETF protocol assignment (192.0.0.0/24) is blocked",
    };
  }
  // 192.0.2.0/24 (TEST-NET-1)
  if (isIp4InCidr(ipInt, "192.0.2.0", 24)) {
    return { blocked: true, reason: "Test network (192.0.2.0/24) is blocked" };
  }
  // 192.168.0.0/16 (RFC 1918 Private)
  if (isIp4InCidr(ipInt, "192.168.0.0", 16)) {
    return {
      blocked: true,
      reason: "Private network (192.168.0.0/16) is blocked",
    };
  }
  // 198.18.0.0/15 (Benchmarking)
  if (isIp4InCidr(ipInt, "198.18.0.0", 15)) {
    return {
      blocked: true,
      reason: "Benchmark network (198.18.0.0/15) is blocked",
    };
  }
  // 198.51.100.0/24 (TEST-NET-2)
  if (isIp4InCidr(ipInt, "198.51.100.0", 24)) {
    return {
      blocked: true,
      reason: "Test network (198.51.100.0/24) is blocked",
    };
  }
  // 203.0.113.0/24 (TEST-NET-3)
  if (isIp4InCidr(ipInt, "203.0.113.0", 24)) {
    return {
      blocked: true,
      reason: "Test network (203.0.113.0/24) is blocked",
    };
  }
  // 224.0.0.0/4 (Multicast)
  if (isIp4InCidr(ipInt, "224.0.0.0", 4)) {
    return {
      blocked: true,
      reason: "Multicast address (224.0.0.0/4) is blocked",
    };
  }
  // 240.0.0.0/4 (Reserved)
  if (isIp4InCidr(ipInt, "240.0.0.0", 4)) {
    return {
      blocked: true,
      reason: "Reserved address (240.0.0.0/4) is blocked",
    };
  }
  // 255.255.255.255/32 (Broadcast)
  if (ip === "255.255.255.255") {
    return { blocked: true, reason: "Broadcast address is blocked" };
  }

  return { blocked: false };
}

/**
 * Check if an IPv6 address is in a blocked/private range.
 */
export function isPrivateOrBlockedIp6(ip: string): {
  blocked: boolean;
  reason?: string;
} {
  if (!net.isIPv6(ip)) return { blocked: true, reason: "Invalid IPv6 address" };

  const normalized = ip.toLowerCase();

  // ::1 (Loopback)
  if (normalized === "::1" || normalized === "0:0:0:0:0:0:0:1") {
    return { blocked: true, reason: "IPv6 loopback (::1) is blocked" };
  }

  // :: (Unspecified)
  if (normalized === "::" || normalized === "0:0:0:0:0:0:0:0") {
    return { blocked: true, reason: "IPv6 unspecified (::) is blocked" };
  }

  // IPv4-mapped IPv6: ::ffff:127.0.0.1 or ::ffff:7f00:1
  if (normalized.startsWith("::ffff:")) {
    const v4Part = normalized.substring(7);
    if (net.isIPv4(v4Part)) {
      const v4Check = isPrivateOrBlockedIp4(v4Part);
      if (v4Check.blocked) {
        return { blocked: true, reason: `IPv4-mapped IPv6: ${v4Check.reason}` };
      }
    }
  }

  // Unique local address (fc00::/7, including fd00::)
  if (normalized.startsWith("fc") || normalized.startsWith("fd")) {
    return {
      blocked: true,
      reason: "IPv6 Unique Local Address (fc00::/7) is blocked",
    };
  }

  // Link-local unicast (fe80::/10)
  if (
    normalized.startsWith("fe8") ||
    normalized.startsWith("fe9") ||
    normalized.startsWith("fea") ||
    normalized.startsWith("feb")
  ) {
    return {
      blocked: true,
      reason: "IPv6 Link-Local address (fe80::/10) is blocked",
    };
  }

  // Multicast (ff00::/8)
  if (normalized.startsWith("ff")) {
    return { blocked: true, reason: "IPv6 Multicast (ff00::/8) is blocked" };
  }

  return { blocked: false };
}

/**
 * Check if an IP address (v4 or v6) is private, loopback, or cloud metadata.
 */
export function isPrivateOrBlockedIp(ip: string): {
  blocked: boolean;
  reason?: string;
} {
  if (net.isIPv4(ip)) {
    return isPrivateOrBlockedIp4(ip);
  }
  if (net.isIPv6(ip)) {
    return isPrivateOrBlockedIp6(ip);
  }
  return { blocked: true, reason: `Invalid IP format: ${ip}` };
}

/**
 * Known cloud metadata and internal hostnames.
 */
const BLOCKED_HOSTNAMES = new Set([
  "localhost",
  "localhost.localdomain",
  "metadata.google.internal",
  "metadata.internal",
  "metadata",
  "instance-data",
]);

/**
 * Validate destination hostname and resolve IP addresses at connection time.
 * This guarantees DNS rebinding resistance by resolving the address and verifying
 * that ALL resolved records are public, safe IPs.
 */
export async function resolveAndValidateDestination(
  host: string,
  resolver: {
    lookup: (
      h: string,
      opts: any,
    ) => Promise<{ address: string; family: number }[]>;
  } = dns,
): Promise<IpValidationResult> {
  const cleanHost = host.trim().toLowerCase();

  // 1. Check known internal hostnames
  if (BLOCKED_HOSTNAMES.has(cleanHost) || cleanHost.endsWith(".localhost")) {
    return {
      valid: false,
      reason: `Blocked internal hostname: ${cleanHost}`,
    };
  }

  // 2. Direct IP literal check
  if (net.isIP(cleanHost)) {
    const check = isPrivateOrBlockedIp(cleanHost);
    if (check.blocked) {
      return {
        valid: false,
        ip: cleanHost,
        reason: check.reason,
      };
    }
    return {
      valid: true,
      ip: cleanHost,
    };
  }

  // 3. Resolve hostname via platform DNS at connection time
  try {
    const addresses = await resolver.lookup(cleanHost, { all: true });

    if (!addresses || addresses.length === 0) {
      return {
        valid: false,
        reason: `DNS resolution returned no addresses for ${cleanHost}`,
      };
    }

    // Every resolved address MUST be safe (prevents dual-homed / rebinding tricks)
    for (const record of addresses) {
      const check = isPrivateOrBlockedIp(record.address);
      if (check.blocked) {
        return {
          valid: false,
          ip: record.address,
          reason: `DNS record ${record.address} for ${cleanHost} is blocked: ${check.reason}`,
        };
      }
    }

    // Return the first validated IP address for pinned connection
    return {
      valid: true,
      ip: addresses[0].address,
    };
  } catch (err: any) {
    return {
      valid: false,
      reason: `DNS lookup failed for ${cleanHost}: ${err.message || err}`,
    };
  }
}
