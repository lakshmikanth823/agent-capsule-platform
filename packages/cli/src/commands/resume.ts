/**
 * capsule resume <app>
 * Resumes a suspended application.
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
      "Could not determine target capsule. Specify <app> or run from a project directory.",
    exitCode: 1,
    hint: "Pass <app> argument or run inside a folder with capsule.manifest.yaml.",
  });
}

export interface ResumeOptions {
  app?: string;
  json?: boolean;
}

export async function resumeCommand(
  appArg?: string,
  options: ResumeOptions = {},
): Promise<void> {
  let appKey: string;
  try {
    appKey = resolveAppKey(appArg || options.app);
  } catch (err: any) {
    outputError(err, options);
  }

  const client = new ApiClient();
  try {
    const result = await client.resumeApp(appKey);
    outputResult(
      result,
      options,
      `Capsule '${appKey}' resumed successfully.\nStatus: ${result.status}`,
    );
  } catch (err: any) {
    outputError(err, options);
  }
}
