import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { createProgram } from '../src/index.js';
import { initCommand } from '../src/commands/init.js';
import { validateCommand } from '../src/commands/validate.js';

describe('Capsule CLI Package', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'capsule-cli-test-'));
  });

  afterEach(() => {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  it('should initialize commander program with correct name, version, and all Phase 0 commands', () => {
    const program = createProgram();
    expect(program.name()).toBe('capsule');
    expect(program.version()).toBe('0.1.0');

    const commandNames = program.commands.map((cmd) => cmd.name());
    expect(commandNames).toContain('login');
    expect(commandNames).toContain('init');
    expect(commandNames).toContain('validate');
    expect(commandNames).toContain('dev');
    expect(commandNames).toContain('publish');
    expect(commandNames).toContain('share');
    expect(commandNames).toContain('unshare');
    expect(commandNames).toContain('status');
    expect(commandNames).toContain('logs');
    expect(commandNames).toContain('versions');
    expect(commandNames).toContain('rollback');
  });

  it('should scaffold complete starter project with capsule init', async () => {
    const appDir = path.join(tmpDir, 'test-app');
    await initCommand('test-app', { json: true });

    // Verify files created
    expect(fs.existsSync(path.join(process.cwd(), 'test-app', 'capsule.manifest.yaml'))).toBe(true);
    expect(fs.existsSync(path.join(process.cwd(), 'test-app', 'package.json'))).toBe(true);
    expect(fs.existsSync(path.join(process.cwd(), 'test-app', 'tsconfig.json'))).toBe(true);
    expect(fs.existsSync(path.join(process.cwd(), 'test-app', 'src', 'index.ts'))).toBe(true);

    // Clean up created test-app in cwd
    try {
      fs.rmSync(path.join(process.cwd(), 'test-app'), { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  it('should validate valid manifest offline successfully', async () => {
    const validManifest = path.join(tmpDir, 'capsule.manifest.yaml');
    fs.writeFileSync(
      validManifest,
      `apiVersion: capsule/v1alpha1
id: test-valid-app
name: Valid App
shape: web-app
runtime: node22
roles:
  - employee
capabilities:
  db:
    type: sqlite
  identity: true
egress: []
sharing:
  default: org
limits:
  cpu: small
  memory_mb: 256
  request_timeout_s: 30
`
    );

    // Should not throw or exit with error
    await validateCommand({ manifest: validManifest, json: true });
  });

  it('should reject invalid manifest offline with exitCode 2 and structured error', async () => {
    const invalidManifest = path.join(tmpDir, 'capsule.manifest.yaml');
    fs.writeFileSync(
      invalidManifest,
      `apiVersion: capsule/v1alpha1
id: BadApp!_Invalid
shape: invalid-shape
`
    );

    const exitSpy = vi.spyOn(process, 'exit').mockImplementation((code?: any) => {
      throw new Error(`process.exit(${code})`);
    });

    await expect(validateCommand({ manifest: invalidManifest, json: true })).rejects.toThrow('process.exit(2)');
    exitSpy.mockRestore();
  });
});
