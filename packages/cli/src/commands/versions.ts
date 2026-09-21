/**
 * capsule versions
 * Lists version history for a capsule.
 */
import fs from 'node:fs';
import path from 'node:path';
import YAML from 'yaml';
import { ApiClient } from '../client.js';
import { outputResult, outputError, CliError } from '../errors.js';

function resolveAppKey(explicitAppKey?: string): string {
  if (explicitAppKey) return explicitAppKey;
  const manifestPath = path.resolve(process.cwd(), 'capsule.manifest.yaml');
  if (fs.existsSync(manifestPath)) {
    try {
      const manifest = YAML.parse(fs.readFileSync(manifestPath, 'utf8'));
      if (manifest?.id) return manifest.id;
    } catch {
      // ignore
    }
  }
  throw new CliError({
    code: 'APP_NOT_SPECIFIED',
    message: 'Could not determine target capsule. Specify --app <appKey> or run from a project directory.',
    exitCode: 1,
    hint: 'Pass --app <appKey> or run inside a folder with capsule.manifest.yaml.',
  });
}

export interface VersionsOptions {
  app?: string;
  json?: boolean;
}

export async function versionsCommand(options: VersionsOptions = {}): Promise<void> {
  let appKey: string;
  try {
    appKey = resolveAppKey(options.app);
  } catch (err: any) {
    outputError(err, options);
  }

  const client = new ApiClient();
  try {
    const versions = await client.listVersions(appKey);

    outputResult(
      {
        app: appKey,
        versions,
      },
      options,
      () => {
        if (!versions || versions.length === 0) {
          console.log(`No published versions found for ${appKey}.`);
          return;
        }

        console.log(`\x1b[1mVERSION  STATUS      PUBLISHED               PUBLISHER        DESCRIPTION\x1b[0m`);
        for (const v of versions) {
          const vNum = String(v.version_number).padEnd(8);
          const status = String(v.status).padEnd(11);
          const date = new Date(v.published_at || v.created_at).toISOString().replace('T', ' ').substring(0, 19).padEnd(23);
          const pub = String(v.publisher_name || v.publisher_agent || 'unknown').padEnd(16);
          const desc = v.change_description || v.description || '(none)';
          console.log(`${vNum} ${status} ${date} ${pub} ${desc}`);
        }
      }
    );
  } catch (err: any) {
    outputError(err, options);
  }
}
