/**
 * capsule status
 * Queries current application status and active deployment.
 */
import fs from "node:fs";
import path from "node:path";
import YAML from "yaml";
import { ApiClient } from "../client.js";
import { outputResult, outputError, CliError } from "../errors.js";

function resolveAppKey(explicitAppKey?: string): string {
  if (explicitAppKey) return explicitAppKey;
  const manifestPath = path.resolve(process.cwd(), "capsule.manifest.yaml");
  if (fs.existsSync(manifestPath)) {
    try {
      const manifest = YAML.parse(fs.readFileSync(manifestPath, "utf8"));
      if (manifest?.id) return manifest.id;
    } catch {
      // ignore
    }
  }
  throw new CliError({
    code: "APP_NOT_SPECIFIED",
    message:
      "Could not determine target capsule. Specify --app <appKey> or run from a project directory.",
    exitCode: 1,
    hint: "Pass --app <appKey> or run inside a folder with capsule.manifest.yaml.",
  });
}

export interface StatusOptions {
  app?: string;
  json?: boolean;
}

export async function statusCommand(
  options: StatusOptions = {},
): Promise<void> {
  let appKey: string;
  try {
    appKey = resolveAppKey(options.app);
  } catch (err: any) {
    outputError(err, options);
  }

  const client = new ApiClient();
  try {
    const app = await client.getApp(appKey);
    const appDomain = process.env.APP_DOMAIN || "apps.localhost";
    const liveUrl = `http://${app.app_key || appKey}.${appDomain}`;

    outputResult(
      {
        id: app.id,
        app_key: app.app_key,
        name: app.name,
        status: app.status,
        shape: app.shape,
        runtime: app.runtime,
        current_version: app.current_version_id ? 1 : null,
        url: liveUrl,
      },
      options,
      () => {
        console.log(`\x1b[1mCapsule: ${app.name} (${app.app_key})\x1b[0m`);
        console.log(`  Status:   \x1b[32m${app.status}\x1b[0m`);
        console.log(`  Shape:    ${app.shape}`);
        console.log(`  Runtime:  ${app.runtime}`);
        console.log(`  Live URL: \x1b[36m${liveUrl}\x1b[0m`);
      },
    );
  } catch (err: any) {
    outputError(err, options);
  }
}
