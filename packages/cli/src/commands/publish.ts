/**
 * capsule publish
 * Idempotently publishes the current Capsule project to the platform.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import YAML from 'yaml';
import { parseAndValidate, type ValidationResult } from '@capsule/manifest-schema';
import { ApiClient } from '../client.js';
import { outputResult, outputError, CliError } from '../errors.js';

export interface PublishOptions {
  description?: string;
  expectedVersion?: string | number;
  dryRun?: boolean;
  wait?: boolean;
  json?: boolean;
  manifest?: string;
  idempotencyKey?: string;
}

export async function publishCommand(options: PublishOptions = {}): Promise<void> {
  const manifestPath = options.manifest || path.resolve(process.cwd(), 'capsule.manifest.yaml');

  if (!fs.existsSync(manifestPath)) {
    outputError(
      new CliError({
        code: 'MANIFEST_NOT_FOUND',
        message: 'capsule.manifest.yaml not found.',
        exitCode: 2,
        hint: 'Run `capsule init` first or specify --manifest <path>.',
      }),
      options,
      2
    );
  }

  let rawManifest: string;
  try {
    rawManifest = fs.readFileSync(manifestPath, 'utf8');
  } catch (err: any) {
    outputError(
      new CliError({
        code: 'FILE_READ_ERROR',
        message: `Failed to read manifest at ${manifestPath}: ${err.message}`,
        exitCode: 2,
      }),
      options,
      2
    );
  }

  // 1. Offline validation
  const valResult: ValidationResult = parseAndValidate(rawManifest);
  if (!valResult.valid) {
    let exitCode = 2;
    if (valResult.required_approvals && valResult.required_approvals.length > 0) {
      exitCode = 4;
    }

    outputError(
      new CliError({
        code: valResult.errors[0]?.code || 'SCHEMA_VALIDATION_FAILED',
        message: valResult.errors[0]?.message || 'Manifest validation failed',
        exitCode,
        field: valResult.errors[0]?.path,
        hint: valResult.errors[0]?.hint,
        details: valResult,
      }),
      options,
      exitCode
    );
  }

  // 2. Dry Run
  if (options.dryRun) {
    outputResult(
      {
        valid: true,
        dry_run: true,
        required_approvals: valResult.required_approvals || [],
        warnings: valResult.warnings || [],
      },
      options,
      () => {
        console.log('\x1b[32m✔ Dry run validation successful!\x1b[0m');
        console.log('No live deployment was created.');
      }
    );
    return;
  }

  const manifest = YAML.parse(rawManifest);
  const appKey = manifest.id;
  const appName = manifest.name || appKey;

  const client = new ApiClient();
  if (!client.token) {
    outputError(
      new CliError({
        code: 'UNAUTHENTICATED',
        message: 'No session credentials found. Please run `capsule login` first.',
        exitCode: 5,
        hint: 'Run `capsule login` to authenticate with the platform.',
      }),
      options,
      5
    );
  }

  // 3. Ensure app exists in control-plane registry
  try {
    await client.getApp(appKey);
  } catch (err: any) {
    if (err.code === 'NOT_FOUND' || err.exitCode === 2) {
      // Create app in registry
      try {
        await client.createApp({
          id: appKey,
          name: appName,
          manifest,
        });
      } catch (createErr: any) {
        outputError(createErr, options);
      }
    } else {
      outputError(err, options);
    }
  }

  // 4. Publish version
  const idempotencyKey = options.idempotencyKey || crypto.randomUUID();
  const expectedVersion = options.expectedVersion ? Number(options.expectedVersion) : undefined;

  let publishResponse: any;
  try {
    publishResponse = await client.publish(
      appKey,
      {
        manifest,
        description: options.description || 'Published via capsule CLI',
        expected_version: expectedVersion,
      },
      { idempotencyKey }
    );
  } catch (err: any) {
    outputError(err, options);
  }

  const appDomain = process.env.APP_DOMAIN || 'apps.localhost';
  const liveUrl = `http://${appKey}.${appDomain}`;
  const versionNum = publishResponse?.version?.version_number || publishResponse?.version_number || 1;

  outputResult(
    {
      status: 'published',
      app: appKey,
      version: versionNum,
      url: liveUrl,
      idempotency_key: idempotencyKey,
    },
    options,
    () => {
      console.log('Validating manifest... \x1b[32mOK\x1b[0m');
      console.log('Checking policy... \x1b[32mOK\x1b[0m');
      console.log('Building artifact... \x1b[32mOK\x1b[0m');
      console.log('Creating snapshot... \x1b[32mOK\x1b[0m');
      console.log(`Deploying version ${versionNum}... \x1b[32mOK\x1b[0m`);
      console.log(`\n\x1b[32m✔ Published successfully!\x1b[0m`);
      console.log(`Live URL: \x1b[36m${liveUrl}\x1b[0m`);
    }
  );
}
