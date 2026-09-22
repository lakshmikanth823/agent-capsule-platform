/**
 * capsule rollback
 * Roll back to a previous version.
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

export interface RollbackOptions {
  version?: number;
  mode?: string;
  confirmDataRestore?: boolean;
  reason?: string;
  app?: string;
  json?: boolean;
}

export async function rollbackCommand(options: RollbackOptions): Promise<void> {
  let appKey: string;
  try {
    appKey = resolveAppKey(options.app);
  } catch (err: any) {
    outputError(err, options);
    return;
  }

  if (options.version === undefined || isNaN(options.version)) {
    outputError(
      new CliError({
        code: "MISSING_VERSION",
        message:
          "Must specify target version to roll back to with --version <n>.",
        exitCode: 1,
        hint: "Example: capsule rollback --version 1",
      }),
      options,
    );
    return;
  }

  // Normalize mode: 'code-only' -> 'code_only', 'code-and-data' -> 'code_and_data'
  let mode: "code_only" | "code_and_data" = "code_only";
  if (options.mode) {
    const m = options.mode.toLowerCase().replace(/-/g, "_");
    if (m === "code_and_data") {
      mode = "code_and_data";
    } else if (m === "code_only") {
      mode = "code_only";
    } else {
      outputError(
        new CliError({
          code: "INVALID_MODE",
          message: `Invalid rollback mode '${options.mode}'. Must be 'code-only' or 'code-and-data'.`,
          exitCode: 1,
          hint: "Use --mode code-only (default) or --mode code-and-data.",
        }),
        options,
      );
      return;
    }
  }

  const client = new ApiClient();

  try {
    const result = await client.rollback(appKey, {
      target_version_number: options.version,
      mode,
      confirm_data_restore: Boolean(options.confirmDataRestore),
      reason: options.reason,
    });

    outputResult(result, options, () => {
      console.log(
        `\x1b[32m✓ Rollback to version ${result.target_version_number} succeeded!\x1b[0m`,
      );
      console.log(
        `  Active Version:    v${result.version_number} (${result.mode})`,
      );
      console.log(
        `  Data Restored:     ${result.data_restored ? "Yes (from snapshot)" : "No (code-only)"}`,
      );
      console.log(`  Recovery Snapshot: ${result.recovery_snapshot_ref}`);
    });
  } catch (err: any) {
    if (err instanceof CliError && err.code === "CONFIRMATION_REQUIRED") {
      const warning = err.details?.detail?.data_loss_warning;
      if (options.json) {
        outputError(err, options);
        return;
      }

      console.log(
        `\x1b[33m\x1b[1mWARNING: This operation restores application data from the snapshot associated with version ${options.version}.\x1b[0m`,
      );
      if (warning) {
        console.log(
          `Current data created after that snapshot may be lost (${warning.current_records} current records, ${warning.estimated_records_lost} estimated lost).`,
        );
        console.log(`A recovery snapshot will be created before rollback.`);
      }
      console.log(
        `\nTo proceed with data restore, pass: \x1b[1mcapsule rollback --version ${options.version} --mode code-and-data --confirm-data-restore\x1b[0m`,
      );
      process.exit(2);
    }
    outputError(err, options);
  }
}
