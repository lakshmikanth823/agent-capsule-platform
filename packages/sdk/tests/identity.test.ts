import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  getIdentity,
  requireIdentity,
  getEmulatorIdentity,
  IdentityVerificationError,
} from '../src/identity.js';
import { createDevIdentityToken } from '../src/emulator.js';

describe('@capsule/sdk - Identity Verification', () => {
  const secret = 'super-secret-test-key-32-chars-long!';
  const audience = 'capsule:test-app';

  beforeEach(() => {
    delete process.env.CAPSULE_EMULATOR;
    delete process.env.NODE_ENV;
  });

  it('should verify valid signed identity token and return IdentityContext', () => {
    const token = createDevIdentityToken({
      userId: 'user-456',
      email: 'alice@example.com',
      orgId: 'org-123',
      roles: ['employee', 'manager'],
      groups: ['engineering'],
      audience,
      secret,
    });

    const identity = getIdentity(token, { secret, audience });
    expect(identity).not.toBeNull();
    expect(identity?.userId).toBe('user-456');
    expect(identity?.email).toBe('alice@example.com');
    expect(identity?.hasRole('manager')).toBe(true);
    expect(identity?.hasRole('hr')).toBe(false);
    expect(identity?.hasAnyRole('hr', 'manager')).toBe(true);
    expect(identity?.isMemberOf('engineering')).toBe(true);
    expect(identity?.isMemberOf('sales')).toBe(false);
  });

  it('should extract identity header from Node.js req object', () => {
    const token = createDevIdentityToken({
      userId: 'user-789',
      roles: ['employee'],
      audience,
      secret,
    });

    const mockReq = {
      headers: {
        'x-capsule-identity': token,
      },
    };

    const identity = getIdentity(mockReq, { secret, audience });
    expect(identity?.userId).toBe('user-789');
  });

  it('should reject forged tokens with invalid signature', () => {
    const token = createDevIdentityToken({
      userId: 'user-456',
      secret: 'wrong-secret-key-that-does-not-match',
      audience,
    });

    expect(getIdentity(token, { secret, audience })).toBeNull();

    expect(() => {
      requireIdentity(token, { secret, audience });
    }).toThrowError(IdentityVerificationError);
  });

  it('should reject tampered tokens', () => {
    const token = createDevIdentityToken({
      userId: 'user-456',
      roles: ['employee'],
      secret,
      audience,
    });

    // Tamper with payload by changing characters in middle part
    const parts = token.split('.');
    parts[1] = Buffer.from(JSON.stringify({ sub: 'admin', roles: ['superadmin'], iss: 'platform', aud: audience }))
      .toString('base64')
      .replace(/=/g, '');
    const tampered = parts.join('.');

    expect(getIdentity(tampered, { secret, audience })).toBeNull();
  });

  it('should reject expired tokens', () => {
    const token = createDevIdentityToken({
      userId: 'user-456',
      secret,
      audience,
      expiresInSeconds: -60, // expired 60 seconds ago
    });

    expect(getIdentity(token, { secret, audience })).toBeNull();

    expect(() => {
      requireIdentity(token, { secret, audience });
    }).toThrow(/expired/i);
  });

  it('should reject tokens with mismatched audience', () => {
    const token = createDevIdentityToken({
      userId: 'user-456',
      secret,
      audience: 'capsule:other-app',
    });

    expect(getIdentity(token, { secret, audience: 'capsule:my-app' })).toBeNull();

    expect(() => {
      requireIdentity(token, { secret, audience: 'capsule:my-app' });
    }).toThrow(/audience mismatch/i);
  });

  it('should provide mock identity in local emulator mode when header is absent', () => {
    process.env.CAPSULE_EMULATOR = 'true';

    const identity = getIdentity(undefined);
    expect(identity).not.toBeNull();
    expect(identity?.userId).toBe('dev-user-001');
    expect(identity?.hasRole('employee')).toBe(true);
    expect(identity?.hasRole('manager')).toBe(true);
  });
});
