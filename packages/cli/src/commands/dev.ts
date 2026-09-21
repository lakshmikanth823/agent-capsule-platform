/**
 * capsule dev
 * Starts local emulator for blessed application shape without platform dependencies.
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { outputError, CliError } from '../errors.js';

export interface DevOptions {
  port?: string | number;
  json?: boolean;
}

export async function devCommand(options: DevOptions = {}): Promise<void> {
  const rootDir = process.cwd();
  const manifestPath = path.join(rootDir, 'capsule.manifest.yaml');

  if (!fs.existsSync(manifestPath)) {
    outputError(
      new CliError({
        code: 'MANIFEST_NOT_FOUND',
        message: 'capsule.manifest.yaml not found in current directory.',
        exitCode: 2,
        hint: 'Run `capsule init` first to create a starter project.',
      }),
      options,
      2
    );
  }

  // 1. Setup local emulator directories in .capsule/
  const capsuleDir = path.join(rootDir, '.capsule');
  const dbPath = path.join(capsuleDir, 'local.db');
  const blobsDir = path.join(capsuleDir, 'blobs');

  fs.mkdirSync(capsuleDir, { recursive: true });
  fs.mkdirSync(blobsDir, { recursive: true });

  const port = options.port || process.env.PORT || 3000;
  const localUrl = `http://localhost:${port}`;

  if (options.json) {
    console.log(
      JSON.stringify(
        {
          status: 'running',
          url: localUrl,
          port: Number(port),
          emulator: true,
          dbPath,
          blobsDir,
        },
        null,
        2
      )
    );
  } else {
    console.log('\x1b[36mStarting Capsule Local Emulator...\x1b[0m');
    console.log(`  Local URL:  ${localUrl}`);
    console.log(`  Database:   ${dbPath}`);
    console.log(`  Blobs:      ${blobsDir}`);
    console.log(`  Identity:   Mock development identity enabled`);
    console.log('\n\x1b[32mPress Ctrl+C to stop.\x1b[0m\n');
  }

  // Determine entrypoint
  let entrypoint = path.join(rootDir, 'dist', 'index.js');
  let cmd = 'node';
  let args = [entrypoint];

  if (!fs.existsSync(entrypoint)) {
    const srcIndex = path.join(rootDir, 'src', 'index.ts');
    if (fs.existsSync(srcIndex)) {
      // Use npx tsx for TypeScript direct execution
      cmd = process.platform === 'win32' ? 'npx.cmd' : 'npx';
      args = ['tsx', srcIndex];
    }
  }

  const child = spawn(cmd, args, {
    stdio: options.json ? 'ignore' : 'inherit',
    env: {
      ...process.env,
      PORT: String(port),
      CAPSULE_EMULATOR: 'true',
      DATABASE_PATH: dbPath,
      CAPSULE_BLOB_DIR: blobsDir,
      NODE_ENV: 'development',
    },
  });

  child.on('error', (err) => {
    outputError(
      new CliError({
        code: 'EMULATOR_SPAWN_FAILED',
        message: `Failed to start local emulator process: ${err.message}`,
        exitCode: 1,
      }),
      options
    );
  });

  // Handle termination signals
  const cleanup = () => {
    child.kill();
    process.exit(0);
  };
  process.on('SIGINT', cleanup);
  process.on('SIGTERM', cleanup);
}
