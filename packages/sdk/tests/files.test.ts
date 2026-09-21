import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { PlatformFileStorage, FileStorageError } from '../src/files.js';

describe('@capsule/sdk - Files (Blob Storage)', () => {
  let tmpDir: string;
  let files: PlatformFileStorage;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'capsule-files-test-'));
    files = new PlatformFileStorage(tmpDir);
  });

  afterEach(() => {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  it('should put, get, and delete files with content type', async () => {
    const putRes = await files.put('documents/report.pdf', 'Sample PDF Content', {
      contentType: 'application/pdf',
    });

    expect(putRes.path).toBe('documents/report.pdf');
    expect(putRes.size).toBe(Buffer.from('Sample PDF Content').length);

    const getRes = await files.get('documents/report.pdf');
    expect(getRes).not.toBeNull();
    expect(getRes?.contentType).toBe('application/pdf');
    expect(getRes?.data.toString('utf8')).toBe('Sample PDF Content');

    const deleted = await files.delete('documents/report.pdf');
    expect(deleted).toBe(true);

    const getAfterDelete = await files.get('documents/report.pdf');
    expect(getAfterDelete).toBeNull();
  });

  it('should list files with prefix filter', async () => {
    await files.put('images/avatar1.png', 'avatar 1');
    await files.put('images/avatar2.png', 'avatar 2');
    await files.put('docs/manual.txt', 'manual text');

    const allFiles = await files.list();
    expect(allFiles).toHaveLength(3);

    const imageFiles = await files.list('images');
    expect(imageFiles).toHaveLength(2);
    expect(imageFiles.map((f) => f.path)).toContain('images/avatar1.png');
    expect(imageFiles.map((f) => f.path)).toContain('images/avatar2.png');
  });

  it('should block path traversal attempts', async () => {
    await expect(files.put('../outside.txt', 'bad')).rejects.toThrowError(FileStorageError);
    await expect(files.put('../../etc/passwd', 'bad')).rejects.toThrowError(FileStorageError);
    await expect(files.get('../outside.txt')).rejects.toThrowError(FileStorageError);
    await expect(files.delete('../outside.txt')).rejects.toThrowError(FileStorageError);
  });
});
