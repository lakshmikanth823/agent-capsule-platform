import crypto from "node:crypto";
import path from "node:path";
import fs from "node:fs";

export interface DevTokenOptions {
  userId?: string;
  email?: string;
  orgId?: string;
  roles?: string[];
  groups?: string[];
  audience?: string;
  secret?: string;
  expiresInSeconds?: number;
}

export function isEmulatorMode(): boolean {
  return (
    process.env.CAPSULE_EMULATOR === "true" ||
    process.env.NODE_ENV === "development" ||
    !process.env.PORT
  );
}

function base64UrlEncode(data: string | Buffer): string {
  const buf = typeof data === "string" ? Buffer.from(data, "utf8") : data;
  return buf
    .toString("base64")
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

/**
 * Creates a signed development identity JWT token for local testing or laptop emulation.
 */
export function createDevIdentityToken(options: DevTokenOptions = {}): string {
  const secret =
    options.secret ||
    process.env.CAPSULE_IDENTITY_SECRET ||
    "dev-emulator-secret-key-1234567890";

  const nowSeconds = Math.floor(Date.now() / 1000);
  const expiresIn = options.expiresInSeconds ?? 86400;

  const header = {
    alg: "HS256",
    typ: "JWT",
    kid: "dev-key",
  };

  const payload = {
    iss: "platform",
    aud: options.audience || "capsule:local-dev",
    sub: options.userId || "dev-user-001",
    org_id: options.orgId || "dev-org-001",
    email: options.email || "developer@example.com",
    groups: options.groups || ["engineering"],
    roles: options.roles || ["employee", "manager"],
    iat: nowSeconds,
    exp: nowSeconds + expiresIn,
  };

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

export interface EmulatorConfig {
  dataDir: string;
  dbPath: string;
  blobsDir: string;
}

/**
 * Initialize local emulator directory structure in `.capsule/`.
 */
export function setupEmulator(rootDir: string = process.cwd()): EmulatorConfig {
  const capsuleDir = path.resolve(rootDir, ".capsule");
  const dbPath = path.join(capsuleDir, "local.db");
  const blobsDir = path.join(capsuleDir, "blobs");

  fs.mkdirSync(capsuleDir, { recursive: true });
  fs.mkdirSync(blobsDir, { recursive: true });

  process.env.CAPSULE_EMULATOR = "true";
  process.env.DATABASE_PATH = dbPath;
  process.env.CAPSULE_BLOB_DIR = blobsDir;

  return {
    dataDir: capsuleDir,
    dbPath,
    blobsDir,
  };
}
