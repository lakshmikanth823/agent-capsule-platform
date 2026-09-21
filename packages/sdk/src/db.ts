import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

export interface DatabaseOptions {
  path?: string;
  maxSizeMb?: number;
}

export interface RunResult {
  changes: number;
  lastInsertRowid: number | bigint;
}

export interface DatabaseClient {
  query<T = any>(sql: string, params?: any[]): T[];
  get<T = any>(sql: string, params?: any[]): T | undefined;
  execute(sql: string, params?: any[]): RunResult;
  exec(sql: string): void;
  transaction<T>(fn: () => T): T;
  exportDatabase(destinationPath: string): void;
  close(): void;
}

let DatabaseSyncClass: any;

function getDatabaseSyncClass(): any {
  if (!DatabaseSyncClass) {
    const require = createRequire(import.meta.url);
    const sqlite = require('node:sqlite');
    DatabaseSyncClass = sqlite.DatabaseSync;
  }
  return DatabaseSyncClass;
}

export class SQLiteDatabase implements DatabaseClient {
  private db: any;
  public readonly dbPath: string;
  public readonly maxSizeMb: number;

  constructor(options: DatabaseOptions = {}) {
    // 1. Determine storage path
    let targetPath = options.path || process.env.DATABASE_PATH;
    if (!targetPath) {
      if (process.env.CAPSULE_EMULATOR === 'true' || process.env.NODE_ENV !== 'production') {
        targetPath = path.resolve(process.cwd(), '.capsule', 'local.db');
      } else {
        targetPath = '/data/app.sqlite';
      }
    }
    this.dbPath = targetPath;

    // 2. Determine size limit
    const envMaxSize = process.env.DB_MAX_SIZE_MB ? Number(process.env.DB_MAX_SIZE_MB) : undefined;
    this.maxSizeMb = options.maxSizeMb || envMaxSize || 50;

    // 3. Ensure directory exists
    const dir = path.dirname(this.dbPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // 4. Initialize DatabaseSync
    const DBClass = getDatabaseSyncClass();
    this.db = new DBClass(this.dbPath);

    // 5. Configure SQLite for high concurrency, single-writer safety, and size limits
    this.db.exec('PRAGMA journal_mode = WAL;');
    this.db.exec('PRAGMA synchronous = NORMAL;');

    // 6. Enforce size limit via max_page_count
    // Default page_size in SQLite is 4096 bytes (4KB)
    const maxPages = Math.floor((this.maxSizeMb * 1024 * 1024) / 4096);
    this.db.exec(`PRAGMA max_page_count = ${maxPages};`);
  }

  /**
   * Execute a query returning all matching rows.
   */
  query<T = any>(sql: string, params: any[] = []): T[] {
    const stmt = this.db.prepare(sql);
    return stmt.all(...params) as T[];
  }

  /**
   * Execute a query returning the first matching row or undefined.
   */
  get<T = any>(sql: string, params: any[] = []): T | undefined {
    const stmt = this.db.prepare(sql);
    const result = stmt.get(...params);
    return (result === undefined ? undefined : result) as T | undefined;
  }

  /**
   * Execute an INSERT, UPDATE, or DELETE statement.
   */
  execute(sql: string, params: any[] = []): RunResult {
    const stmt = this.db.prepare(sql);
    const result = stmt.run(...params);
    return {
      changes: Number(result.changes),
      lastInsertRowid: result.lastInsertRowid,
    };
  }

  /**
   * Execute raw SQL statements (e.g. schema creation).
   */
  exec(sql: string): void {
    this.db.exec(sql);
  }

  /**
   * Execute a transaction with immediate write locking (single-writer guarantee).
   */
  transaction<T>(fn: () => T): T {
    this.db.exec('BEGIN IMMEDIATE;');
    try {
      const result = fn();
      this.db.exec('COMMIT;');
      return result;
    } catch (err) {
      try {
        this.db.exec('ROLLBACK;');
      } catch {
        // ignore rollback failure if transaction already aborted
      }
      throw err;
    }
  }

  /**
   * Cleanly export the database to a destination file without lock contention using VACUUM INTO.
   */
  exportDatabase(destinationPath: string): void {
    const resolvedDest = path.resolve(destinationPath);
    const destDir = path.dirname(resolvedDest);
    if (!fs.existsSync(destDir)) {
      fs.mkdirSync(destDir, { recursive: true });
    }
    if (fs.existsSync(resolvedDest)) {
      fs.unlinkSync(resolvedDest);
    }
    const escaped = resolvedDest.replace(/'/g, "''");
    this.db.exec(`VACUUM INTO '${escaped}';`);
  }

  /**
   * Close the database connection.
   */
  close(): void {
    if (this.db) {
      this.db.close();
    }
  }
}

let defaultDbInstance: SQLiteDatabase | null = null;

/**
 * Get or initialize the primary SQLite database client.
 */
export function getDatabase(options?: DatabaseOptions): SQLiteDatabase {
  if (!defaultDbInstance || options) {
    const instance = new SQLiteDatabase(options);
    if (!defaultDbInstance) {
      defaultDbInstance = instance;
    }
    return instance;
  }
  return defaultDbInstance;
}
