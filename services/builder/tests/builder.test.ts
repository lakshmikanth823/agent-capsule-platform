import { describe, it, expect } from 'vitest';
import { validateBuildOptions } from '../src/index.js';

describe('Isolated Builder Service', () => {
  it('should validate build options correctly', async () => {
    const valid = await validateBuildOptions({
      sourceDir: '/tmp/source',
      outputArtifactPath: '/tmp/artifacts/v1.tar.gz',
    });
    expect(valid).toBe(true);

    const invalid = await validateBuildOptions({
      sourceDir: '',
      outputArtifactPath: '',
    });
    expect(invalid).toBe(false);
  });
});
