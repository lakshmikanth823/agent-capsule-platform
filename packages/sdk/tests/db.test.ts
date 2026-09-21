import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { SQLiteDatabase, getDatabase } from '../src/db.js';

describe('@capsule/sdk - Database (SQLite)', () => {
  let tmpDir: string;
  let dbPath: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'capsule-db-test-'));
    dbPath = path.join(tmpDir, 'test.sqlite');
  });

  afterEach(() => {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  it('should initialize database with WAL mode and size limits', () => {
    const db = new SQLiteDatabase({ path: dbPath, maxSizeMb: 10 });
    expect(fs.existsSync(dbPath)).toBe(true);

    // Verify WAL mode
    const journalMode = db.get('PRAGMA journal_mode;');
    expect(journalMode?.journal_mode).toBe('wal');

    // Verify max page count corresponds to 10MB (10 * 1024 * 1024 / 4096 = 2560 pages)
    const pageCount = db.get('PRAGMA max_page_count;');
    expect(pageCount?.max_page_count).toBe(2560);

    db.close();
  });

  it('should execute DDL, INSERT, and queries correctly', () => {
    const db = new SQLiteDatabase({ path: dbPath });

    db.exec(`
      CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL
      );
    `);

    const result = db.execute('INSERT INTO users (name, email) VALUES (?, ?)', ['Alice', 'alice@example.com']);
    expect(result.changes).toBe(1);
    expect(Number(result.lastInsertRowid)).toBe(1);

    const user = db.get<{ id: number; name: string; email: string }>('SELECT * FROM users WHERE id = ?', [1]);
    expect(user).toBeDefined();
    expect(user?.name).toBe('Alice');
    expect(user?.email).toBe('alice@example.com');

    const allUsers = db.query('SELECT * FROM users');
    expect(allUsers).toHaveLength(1);

    db.close();
  });

  it('should execute transactions with immediate lock (single-writer guarantee)', () => {
    const db = new SQLiteDatabase({ path: dbPath });

    db.exec('CREATE TABLE counter (val INTEGER); INSERT INTO counter VALUES (0);');

    db.transaction(() => {
      db.execute('UPDATE counter SET val = val + 1');
      db.execute('UPDATE counter SET val = val + 1');
    });

    const counter = db.get<{ val: number }>('SELECT val FROM counter');
    expect(counter?.val).toBe(2);

    // Rollback test
    expect(() => {
      db.transaction(() => {
        db.execute('UPDATE counter SET val = val + 10');
        throw new Error('Simulated failure');
      });
    }).toThrow('Simulated failure');

    const counterAfterRollback = db.get<{ val: number }>('SELECT val FROM counter');
    expect(counterAfterRollback?.val).toBe(2);

    db.close();
  });

  it('should enforce size limit and reject writes exceeding max_page_count', () => {
    // Set an ultra-low max size: 1MB = 256 pages (4096 bytes per page)
    const db = new SQLiteDatabase({ path: dbPath, maxSizeMb: 1 });

    db.exec('CREATE TABLE big_data (id INTEGER PRIMARY KEY, content BLOB);');

    // Fill up database until it exceeds max page count
    // A 100KB buffer per insert will quickly hit the 1MB limit
    const chunk = Buffer.alloc(100 * 1024, 'x');

    let exceeded = false;
    try {
      for (let i = 0; i < 20; i++) {
        db.execute('INSERT INTO big_data (content) VALUES (?)', [chunk]);
      }
    } catch (err: any) {
      exceeded = true;
      expect(err.message).toMatch(/database or disk is full|SQLITE_FULL/i);
    }

    expect(exceeded).toBe(true);
    db.close();
  });

  it('should export clean database using VACUUM INTO', () => {
    const db = new SQLiteDatabase({ path: dbPath });
    db.exec('CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT);');
    db.execute('INSERT INTO notes (text) VALUES (?)', ['Note 1']);

    const exportPath = path.join(tmpDir, 'backup', 'exported.sqlite');
    db.exportDatabase(exportPath);

    expect(fs.existsSync(exportPath)).toBe(true);

    // Open exported db and verify contents
    const exportedDb = new SQLiteDatabase({ path: exportPath });
    const note = exportedDb.get<{ text: string }>('SELECT text FROM notes WHERE id = 1');
    expect(note?.text).toBe('Note 1');

    db.close();
    exportedDb.close();
  });
});
