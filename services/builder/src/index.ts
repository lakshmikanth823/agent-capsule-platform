/**
 * @capsule/builder
 * Isolated builder for compiling Node.js 22 TypeScript applications into versioned artifacts.
 */

export interface BuildOptions {
  sourceDir: string;
  outputArtifactPath: string;
  timeoutMs?: number;
}

export interface BuildResult {
  success: boolean;
  artifactRef?: string;
  error?: string;
}

export async function validateBuildOptions(options: BuildOptions): Promise<boolean> {
  return Boolean(options.sourceDir && options.outputArtifactPath);
}
