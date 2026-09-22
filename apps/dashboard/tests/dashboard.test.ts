import { describe, it, expect } from 'vitest';
import { dashboardAppVersion, type DashboardAppSummary } from '../src/index.js';

describe('Dashboard App Package', () => {
  it('should export correct version', () => {
    expect(dashboardAppVersion).toBe('0.1.0');
  });

  it('should conform to DashboardAppSummary interface', () => {
    const app: DashboardAppSummary = {
      id: 'leave-tracker',
      name: 'Leave Tracker',
      version: 1,
      status: 'active',
      ownerEmail: 'alice@example.com',
      updatedAt: '2026-09-21T00:00:00Z',
    };
    expect(app.status).toBe('active');
  });

  it('should export Environment Profile API methods and types', async () => {
    const { api, EnvironmentProfileScreen } = await import('../src/index.js');
    expect(typeof api.getEnvironmentProfile).toBe('function');
    expect(typeof api.previewProfileDiff).toBe('function');
    expect(typeof api.updateEnvironmentProfile).toBe('function');
    expect(typeof api.getEffectivePolicy).toBe('function');
    expect(typeof EnvironmentProfileScreen).toBe('function');
  });
});

