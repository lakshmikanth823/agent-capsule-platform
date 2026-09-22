import crypto from "node:crypto";

export interface JwtHeader {
  alg: string;
  typ: string;
  kid?: string;
}

function base64UrlEncode(data: string | Buffer): string {
  const buf = typeof data === "string" ? Buffer.from(data, "utf8") : data;
  return buf
    .toString("base64")
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function base64UrlDecode(str: string): string {
  let base64 = str.replace(/-/g, "+").replace(/_/g, "/");
  while (base64.length % 4 !== 0) {
    base64 += "=";
  }
  return Buffer.from(base64, "base64").toString("utf8");
}

/**
 * Sign a JWT using HMAC-SHA256 and include the key ID (`kid`) in header.
 */
export function signJwt(
  payload: Record<string, any>,
  secret: string,
  kid?: string,
): string {
  const header: JwtHeader = { alg: "HS256", typ: "JWT" };
  if (kid) {
    header.kid = kid;
  }

  const encodedHeader = base64UrlEncode(JSON.stringify(header));
  const encodedPayload = base64UrlEncode(JSON.stringify(payload));
  const dataToSign = `${encodedHeader}.${encodedPayload}`;

  const signature = crypto
    .createHmac("sha256", secret)
    .update(dataToSign)
    .digest();
  const encodedSignature = base64UrlEncode(signature);

  return `${dataToSign}.${encodedSignature}`;
}

/**
 * Verify a JWT using a set of valid keys (supporting key rotation).
 * Checks signature and expiration timestamp (`exp`).
 */
export function verifyJwt<T = Record<string, any>>(
  token: string,
  keys: Record<string, string>,
): { header: JwtHeader; payload: T } | null {
  if (!token || typeof token !== "string") return null;

  const parts = token.split(".");
  if (parts.length !== 3) return null;

  const [encodedHeader, encodedPayload, encodedSignature] = parts;

  try {
    const header: JwtHeader = JSON.parse(base64UrlDecode(encodedHeader));
    const payload: any = JSON.parse(base64UrlDecode(encodedPayload));

    // Determine verification secret from `kid` or default
    let secret = header.kid ? keys[header.kid] : undefined;
    if (!secret) {
      // Fall back to first key if no kid or specific kid not found
      const firstKey = Object.values(keys)[0];
      if (!firstKey) return null;
      secret = firstKey;
    }

    // Verify HMAC-SHA256 signature
    const dataToSign = `${encodedHeader}.${encodedPayload}`;
    const expectedSig = crypto
      .createHmac("sha256", secret)
      .update(dataToSign)
      .digest();
    const expectedEncodedSig = base64UrlEncode(expectedSig);

    // Constant-time comparison
    if (
      !crypto.timingSafeEqual(
        Buffer.from(encodedSignature),
        Buffer.from(expectedEncodedSig),
      )
    ) {
      return null;
    }

    // Check expiration if present
    if (payload.exp && typeof payload.exp === "number") {
      const nowSeconds = Math.floor(Date.now() / 1000);
      if (nowSeconds >= payload.exp) {
        return null; // Expired
      }
    }

    return { header, payload };
  } catch {
    return null;
  }
}
