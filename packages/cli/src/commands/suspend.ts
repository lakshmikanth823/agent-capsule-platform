/**
 * capsule suspend <app>
 * Instantly suspends an application.
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

export interface SuspendOptions {
  reason?: string;
  app?: string;
  json?: boolean;
}

export async function suspendCommand(
  appArg?: string,
  options: SuspendOptions = {},
): Promise<void> {
  let appKey: string;
  try {
    appKey = resolveAppKey(appArg || options.app);
  } catch (err: any) {
    outputError(err, options);
  }

  const reason = options.reason?.trim();
  if (!reason) {
    outputError(
      new CliError({
        code: "REASON_REQUIRED",
        message:
          'A non-empty suspension reason is required (use --reason "<reason>").',
        exitCode: 2,
        hint: "Provide --reason to explain why this capsule is being suspended.",
      }),
      options,
    );
  }

  const client = new ApiClient();
  try {
    const result = await client.suspendApp(appKey, reason);
    outputResult(
      result,
      options,
      `Capsule '${appKey}' suspended successfully.\nReason: ${reason}\nStatus: ${result.status}`,
    );
  } catch (err: any) {
    outputError(err, options);
  }
}
