import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createProgram } from '../src/index.js';
import { auditVerifyCommand, auditListCommand, auditExportCommand, auditRetentionCommand } from '../src/commands/audit.js';
import { ApiClient } from '../src/client.js';

describe('Capsule CLI Audit Commands (Prompt 19)', () => {
  it('should register audit command and all subcommands in CLI program', () => {
    const program = createProgram();
    const auditCmd = program.commands.find((c) => c.name() === 'audit');
    expect(auditCmd).toBeDefined();

    const subcommands = auditCmd!.commands.map((c) => c.name());
    expect(subcommands).toContain('list');
    expect(subcommands).toContain('verify');
    expect(subcommands).toContain('export');
    expect(subcommands).toContain('retention');
  });

  it('should call verify endpoint and display cryptographic chain report', async () => {
    const requestMock = vi.spyOn(ApiClient.prototype, 'request').mockImplementation(async (endpoint: string) => {
      if (endpoint === '/v1/auth/me') {
        return { organization_id: 'test-org-uuid-123' };
      }
      if (endpoint === '/v1/organizations/test-org-uuid-123/audit/verify') {
        return {
          valid: true,
          organization_id: 'test-org-uuid-123',
          total_events: 42,
          first_sequence: 1,
          last_sequence: 42,
          tampered_at_sequence: null,
          checkpoint: null,
        };
      }
      throw new Error(`Unexpected endpoint: ${endpoint}`);
    });

    const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

    await auditVerifyCommand({ json: false });

    expect(requestMock).toHaveBeenCalledWith('/v1/auth/me');
    expect(requestMock).toHaveBeenCalledWith('/v1/organizations/test-org-uuid-123/audit/verify', { method: 'POST' });
    expect(consoleSpy).toHaveBeenCalled();
    const logged = consoleSpy.mock.calls.map((c) => c[0]).join(' ');
    expect(logged).toContain('VALID');
    expect(logged).toContain('42');

    requestMock.mockRestore();
    consoleSpy.mockRestore();
  });

  it('should format tamper detection warning when chain verification fails', async () => {
    const requestMock = vi.spyOn(ApiClient.prototype, 'request').mockImplementation(async (endpoint: string) => {
      if (endpoint === '/v1/auth/me') {
        return { organization_id: 'test-org-uuid-123' };
      }
      if (endpoint === '/v1/organizations/test-org-uuid-123/audit/verify') {
        return {
          valid: false,
          organization_id: 'test-org-uuid-123',
          tampered_at_sequence: 7,
          reason: 'Hash mismatch at sequence 7: row modified in database',
        };
      }
      throw new Error(`Unexpected endpoint: ${endpoint}`);
    });

    const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

    await auditVerifyCommand({ json: false });

    const logged = consoleSpy.mock.calls.map((c) => c[0]).join(' ');
    expect(logged).toContain('TAMPERED / BROKEN');
    expect(logged).toContain('#7');

    requestMock.mockRestore();
    consoleSpy.mockRestore();
  });

  it('should call retention endpoint and report pruned count', async () => {
    const requestMock = vi.spyOn(ApiClient.prototype, 'request').mockImplementation(async (endpoint: string) => {
      if (endpoint === '/v1/auth/me') {
        return { organization_id: 'test-org-uuid-123' };
      }
      if (endpoint === '/v1/organizations/test-org-uuid-123/audit/retention/enforce') {
        return {
          organization_id: 'test-org-uuid-123',
          retention_days: 90,
          purged_count: 14,
          checkpoint: {
            sequence: 14,
            hash: 'abcd1234efgh5678abcd1234efgh5678abcd1234efgh5678abcd1234efgh5678',
          },
        };
      }
      throw new Error(`Unexpected endpoint: ${endpoint}`);
    });

    const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

    await auditRetentionCommand({ json: false });

    const logged = consoleSpy.mock.calls.map((c) => c[0]).join(' ');
    expect(logged).toContain('Pruned Records: 14');
    expect(logged).toContain('90 days');

    requestMock.mockRestore();
    consoleSpy.mockRestore();
  });
});
