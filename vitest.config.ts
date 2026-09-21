import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    server: {
      deps: {
        external: ['node:sqlite'],
      },
    },
    include: [
      'packages/*/tests/**/*.test.ts',
      'services/*/tests/**/*.test.ts',
      'apps/*/tests/**/*.test.ts',
      'tests/**/*.test.ts',
    ],
  },
  ssr: {
    external: ['node:sqlite'],
  },
});
