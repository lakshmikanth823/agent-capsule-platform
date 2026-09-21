import { describe, it, expect } from 'vitest';
import { parseIdentityHeader, sdkVersion } from '../src/index.js';

describe('@capsule/sdk Package', () => {
  it('should export correct sdkVersion', () => {
    expect(sdkVersion).toBe('0.1.0');
  });

  it('should parse valid identity header JSON', () => {
    const raw = JSON.stringify({
      iss: 'platform',
      aud: 'capsule:test',
      sub: 'user-123',
      org_id: 'org-456',
      groups: ['eng'],
      roles: ['employee'],
      iat: 1000,
      exp: 2000,
    });
    const parsed = parseIdentityHeader(raw);
    expect(parsed?.sub).toBe('user-123');
    expect(parsed?.roles).toContain('employee');
  });

  it('should return null for invalid identity header', () => {
    expect(parseIdentityHeader(undefined)).toBeNull();
    expect(parseIdentityHeader('invalid-json')).toBeNull();
  });
});
