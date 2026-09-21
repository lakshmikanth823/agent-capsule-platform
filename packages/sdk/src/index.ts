/**
 * @capsule/sdk
 * Platform SDK for the blessed Node.js 22 + TypeScript application shape.
 * Note: The platform, not this SDK, is the security boundary.
 */
import { createRequire } from 'node:module';

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

export interface DatabaseSync {
  exec(sql: string): void;
  prepare(sql: string): {
    all(...params: any[]): any[];
    get(...params: any[]): any;
    run(...params: any[]): { changes: number | bigint; lastInsertRowid: number | bigint };
  };
  close(): void;
}

let DatabaseSyncClass: any;

export function getDatabase(dbPath?: string): DatabaseSync {
  const targetPath = dbPath || process.env.DATABASE_PATH || '/data/app.sqlite';
  if (!DatabaseSyncClass) {
    const require = createRequire(import.meta.url);
    const sqlite = require('node:sqlite');
    DatabaseSyncClass = sqlite.DatabaseSync;
  }
  const db = new DatabaseSyncClass(targetPath) as DatabaseSync;
  db.exec('PRAGMA journal_mode = WAL;');
  db.exec('PRAGMA synchronous = NORMAL;');
  return db;
}

export const sdkVersion = '0.1.0';
