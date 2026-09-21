import { describe, it, expect } from 'vitest';
import { extractSubdomainCapsuleId } from '../src/index.js';

describe('Edge Proxy Service', () => {
  it('should extract capsule id from subdomain on localhost', () => {
    expect(extractSubdomainCapsuleId('leave-tracker.localhost:8080')).toBe('leave-tracker');
    expect(extractSubdomainCapsuleId('team-dashboard.localhost')).toBe('team-dashboard');
  });

  it('should return null for bare localhost without subdomain', () => {
    expect(extractSubdomainCapsuleId('localhost:8080')).toBeNull();
  });
});
