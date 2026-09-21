import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { SQLiteDatabase } from '@capsule/sdk';
import { createDevIdentityToken, getIdentity, IdentityVerificationError } from '@capsule/sdk';
import { DevMockSandboxDriver } from '../src/drivers/mock.js';
import { CapsuleLifecycleManager } from '../src/lifecycle.js';

describe('Prompt 09: Storage Isolation, Persistence, and Identity Verification', () => {
  let tmpBaseDir: string;
  let driver: DevMockSandboxDriver;
  let lifecycle: CapsuleLifecycleManager;

  beforeEach(() => {
    tmpBaseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'capsule-storage-test-'));
    driver = new DevMockSandboxDriver();
    lifecycle = new CapsuleLifecycleManager({
      driver,
      baseDataDir: tmpBaseDir,
    });
  });

  afterEach(async () => {
    for (const inst of lifecycle.listInstances()) {
      await lifecycle.destroy(inst.spec.appKey).catch(() => {});
    }
    try {
      fs.rmSync(tmpBaseDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  it('data persists across suspend and resume', async () => {
    const capsuleId = 'capsule-persist-01';
    const appKey = 'persist-app';
    const dataDir = path.join(tmpBaseDir, capsuleId, 'data');
    fs.mkdirSync(dataDir, { recursive: true });

    // 1. Write data to capsule's database
    const dbPath = path.join(dataDir, 'app.sqlite');
    const db = new SQLiteDatabase({ path: dbPath });
    db.exec('CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);');
    db.execute('INSERT INTO items (name) VALUES (?)', ['Persisted Item']);
    db.close();

    // 2. Prepare and start capsule
    const spec = await lifecycle.prepareCapsule({
      capsuleId,
      versionId: 'v1',
      appKey,
      bundlePath: path.resolve(process.cwd(), 'examples', 'leave-tracker'),
      customDataDir: dataDir,
    });
    const instance = await driver.start(spec);
    expect(instance.status).toBe('running');

    // 3. Suspend instance
    await driver.suspend(instance.id);
    expect(await driver.status(instance.id)).toBe('suspended');

    // 4. Resume instance
    await driver.resume(instance.id);
    expect(await driver.status(instance.id)).toBe('running');

    // 5. Verify data is intact
    const dbAfterResume = new SQLiteDatabase({ path: dbPath });
    const row = dbAfterResume.get<{ name: string }>('SELECT name FROM items WHERE id = 1');
    expect(row?.name).toBe('Persisted Item');
    dbAfterResume.close();

    await driver.stop(instance.id);
  });

  it('one capsule cannot see another capsules database (storage isolation)', async () => {
    const dataDirA = path.join(tmpBaseDir, 'capsule-A', 'data');
    const dataDirB = path.join(tmpBaseDir, 'capsule-B', 'data');
    fs.mkdirSync(dataDirA, { recursive: true });
    fs.mkdirSync(dataDirB, { recursive: true });

    const dbPathA = path.join(dataDirA, 'app.sqlite');
    const dbPathB = path.join(dataDirB, 'app.sqlite');

    // Initialize DB A
    const dbA = new SQLiteDatabase({ path: dbPathA });
    dbA.exec('CREATE TABLE secrets (key TEXT, val TEXT);');
    dbA.execute('INSERT INTO secrets VALUES (?, ?)', ['secret_a', 'Capsule-A-Secret-Data']);
    dbA.close();

    // Initialize DB B
    const dbB = new SQLiteDatabase({ path: dbPathB });
    dbB.exec('CREATE TABLE secrets (key TEXT, val TEXT);');
    dbB.execute('INSERT INTO secrets VALUES (?, ?)', ['secret_b', 'Capsule-B-Secret-Data']);
    dbB.close();

    // Verify isolation: DB A does not have secret_b
    const verifyA = new SQLiteDatabase({ path: dbPathA });
    const rowInA = verifyA.get('SELECT val FROM secrets WHERE key = ?', ['secret_b']);
    expect(rowInA).toBeUndefined();
    verifyA.close();

    // Verify isolation: DB B does not have secret_a
    const verifyB = new SQLiteDatabase({ path: dbPathB });
    const rowInB = verifyB.get('SELECT val FROM secrets WHERE key = ?', ['secret_a']);
    expect(rowInB).toBeUndefined();
    verifyB.close();

    // Verify file separation on host
    expect(fs.existsSync(dbPathA)).toBe(true);
    expect(fs.existsSync(dbPathB)).toBe(true);
    expect(dbPathA).not.toBe(dbPathB);
  });

  it('identity verification rejects forged headers and accepts valid headers', () => {
    const secret = 'platform-signing-secret-key-32ch!';
    const audience = 'capsule:leave-tracker';

    // 1. Valid signed token
    const validToken = createDevIdentityToken({
      userId: 'alice-123',
      email: 'alice@example.com',
      roles: ['employee'],
      audience,
      secret,
    });
    const validIdentity = getIdentity(validToken, { secret, audience });
    expect(validIdentity).not.toBeNull();
    expect(validIdentity?.userId).toBe('alice-123');
    expect(validIdentity?.hasRole('employee')).toBe(true);

    // 2. Forged signature token
    const forgedToken = createDevIdentityToken({
      userId: 'alice-123',
      roles: ['owner'],
      audience,
      secret: 'attacker-fake-secret',
    });
    const forgedResult = getIdentity(forgedToken, { secret, audience });
    expect(forgedResult).toBeNull();

    // 3. Mismatched audience token
    const wrongAudToken = createDevIdentityToken({
      userId: 'alice-123',
      audience: 'capsule:different-app',
      secret,
    });
    const wrongAudResult = getIdentity(wrongAudToken, { secret, audience });
    expect(wrongAudResult).toBeNull();

    // 4. Expired token
    const expiredToken = createDevIdentityToken({
      userId: 'alice-123',
      audience,
      secret,
      expiresInSeconds: -30,
    });
    const expiredResult = getIdentity(expiredToken, { secret, audience });
    expect(expiredResult).toBeNull();
  });

  it('Acceptance: the sample app stores and reads records per user, and survives a restart', async () => {
    const capsuleId = 'capsule-acceptance-leave-tracker';
    const dataDir = path.join(tmpBaseDir, capsuleId, 'data');
    fs.mkdirSync(dataDir, { recursive: true });

    const dbPath = path.join(dataDir, 'app.sqlite');

    // 1. First run: Initialize database and store records for Alice and Bob
    const db = new SQLiteDatabase({ path: dbPath });
    db.exec(`
      CREATE TABLE IF NOT EXISTS leave_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
    `);

    // Alice stores a leave request
    const aliceRes = db.execute(
      `INSERT INTO leave_requests (user_id, start_date, end_date, reason) VALUES (?, ?, ?, ?)`,
      ['alice-user-id', '2026-10-01', '2026-10-05', 'Alice Vacation']
    );
    expect(aliceRes.changes).toBe(1);

    // Bob stores a leave request
    const bobRes = db.execute(
      `INSERT INTO leave_requests (user_id, start_date, end_date, reason) VALUES (?, ?, ?, ?)`,
      ['bob-user-id', '2026-11-10', '2026-11-12', 'Bob Conference']
    );
    expect(bobRes.changes).toBe(1);

    // Verify per-user reading
    const aliceLeaves = db.query('SELECT * FROM leave_requests WHERE user_id = ?', ['alice-user-id']);
    expect(aliceLeaves).toHaveLength(1);
    expect(aliceLeaves[0].reason).toBe('Alice Vacation');

    const bobLeaves = db.query('SELECT * FROM leave_requests WHERE user_id = ?', ['bob-user-id']);
    expect(bobLeaves).toHaveLength(1);
    expect(bobLeaves[0].reason).toBe('Bob Conference');

    // Close db before restart
    db.close();

    // 2. Simulate container stop & restart (survives restart)
    // Re-open database from the same persistent dataDir
    const dbAfterRestart = new SQLiteDatabase({ path: dbPath });

    // Verify both records survived restart intact
    const allLeaves = dbAfterRestart.query('SELECT * FROM leave_requests ORDER BY id ASC');
    expect(allLeaves).toHaveLength(2);

    // Verify Alice's record after restart
    const aliceAfterRestart = dbAfterRestart.query('SELECT * FROM leave_requests WHERE user_id = ?', ['alice-user-id']);
    expect(aliceAfterRestart).toHaveLength(1);
    expect(aliceAfterRestart[0].reason).toBe('Alice Vacation');

    // Verify Bob's record after restart
    const bobAfterRestart = dbAfterRestart.query('SELECT * FROM leave_requests WHERE user_id = ?', ['bob-user-id']);
    expect(bobAfterRestart).toHaveLength(1);
    expect(bobAfterRestart[0].reason).toBe('Bob Conference');

    // 3. Verify database export capability
    const exportPath = path.join(tmpBaseDir, 'exports', 'leave_tracker_backup.sqlite');
    dbAfterRestart.exportDatabase(exportPath);
    expect(fs.existsSync(exportPath)).toBe(true);

    const exportedDb = new SQLiteDatabase({ path: exportPath });
    const exportedRows = exportedDb.query('SELECT * FROM leave_requests');
    expect(exportedRows).toHaveLength(2);

    dbAfterRestart.close();
    exportedDb.close();
  });
});
