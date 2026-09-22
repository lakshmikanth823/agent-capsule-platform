import { describe, it, expect, vi, beforeEach } from 'vitest';
import { suspendCommand } from '../src/commands/suspend.js';
import { resumeCommand } from '../src/commands/resume.js';
import { ApiClient } from '../src/client.js';

vi.mock('../src/client.js');

describe('CLI Suspend & Resume Commands (Prompt 23)', () => {
  let mockClient: any;

  beforeEach(() => {
    vi.clearAllMocks();
    mockClient = {
      suspendApp: vi.fn(),
      resumeApp: vi.fn(),
    };
    (ApiClient as any).mockImplementation(function() {
      return mockClient;
    });
  });

  it('should require a non-empty reason to suspend', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const exitSpy = vi.spyOn(process, 'exit').mockImplementation((() => {}) as any);

    await suspendCommand('test-app', { json: true });

    expect(errorSpy).toHaveBeenCalled();
    const errorOutput = JSON.parse(errorSpy.mock.calls[0][0]);
    expect(errorOutput.error.code).toBe('REASON_REQUIRED');

    errorSpy.mockRestore();
    exitSpy.mockRestore();
  });

  it('should successfully suspend an app with valid reason', async () => {
    mockClient.suspendApp.mockResolvedValueOnce({
      id: 'app-123',
      app_key: 'test-app',
      status: 'suspended',
      suspension_reason: 'Malicious activity detected',
      message: "Capsule 'test-app' suspended successfully.",
    });

    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

    await suspendCommand('test-app', {
      reason: 'Malicious activity detected',
      json: true,
    });

    expect(mockClient.suspendApp).toHaveBeenCalledWith('test-app', 'Malicious activity detected');
    expect(logSpy).toHaveBeenCalled();
    const result = JSON.parse(logSpy.mock.calls[0][0]);
    expect(result.status).toBe('suspended');
    expect(result.suspension_reason).toBe('Malicious activity detected');

    logSpy.mockRestore();
  });

  it('should successfully resume a suspended app', async () => {
    mockClient.resumeApp.mockResolvedValueOnce({
      id: 'app-123',
      app_key: 'test-app',
      status: 'active',
      message: "Capsule 'test-app' resumed successfully.",
    });

    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

    await resumeCommand('test-app', { json: true });

    expect(mockClient.resumeApp).toHaveBeenCalledWith('test-app');
    expect(logSpy).toHaveBeenCalled();
    const result = JSON.parse(logSpy.mock.calls[0][0]);
    expect(result.status).toBe('active');

    logSpy.mockRestore();
  });
});
