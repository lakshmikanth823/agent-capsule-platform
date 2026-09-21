import { describe, it, expect } from 'vitest';
import { isManifestShapeValid, isRuntimeValid, type CapsuleManifest } from '../src/index.js';

describe('Manifest Schema Module', () => {
  it('should validate blessed shape web-app', () => {
    expect(isManifestShapeValid('web-app')).toBe(true);
    expect(isManifestShapeValid('worker')).toBe(false);
  });

  it('should validate blessed runtime node22', () => {
    expect(isRuntimeValid('node22')).toBe(true);
    expect(isRuntimeValid('python312')).toBe(false);
  });

  it('should conform to CapsuleManifest interface', () => {
    const manifest: CapsuleManifest = {
      apiVersion: 'capsule/v1alpha1',
      id: 'test-app',
      name: 'Test App',
      shape: 'web-app',
      runtime: 'node22',
    };
    expect(manifest.id).toBe('test-app');
    expect(manifest.shape).toBe('web-app');
  });
});
