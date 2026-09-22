/**
 * capsule validate
 * Fully offline manifest validation using @capsule/manifest-schema.
 */
import fs from "node:fs";
import path from "node:path";
import {
  parseAndValidate,
  type ValidationResult,
} from "@capsule/manifest-schema";
import { outputResult, outputError, CliError } from "../errors.js";

export interface ValidateOptions {
  manifest?: string;
  json?: boolean;
}

export async function validateCommand(
  options: ValidateOptions = {},
): Promise<void> {
  const manifestPath =
    options.manifest || path.resolve(process.cwd(), "capsule.manifest.yaml");

  if (!fs.existsSync(manifestPath)) {
    outputError(
      new CliError({
        code: "MANIFEST_NOT_FOUND",
        message: `Manifest file not found at ${manifestPath}`,
        exitCode: 2,
        hint: "Run `capsule init` to create a starter capsule.manifest.yaml or pass --manifest <path>.",
      }),
      options,
      2,
    );
  }

  let content: string;
  try {
    content = fs.readFileSync(manifestPath, "utf8");
  } catch (err: any) {
    outputError(
      new CliError({
        code: "FILE_READ_ERROR",
        message: `Failed to read manifest at ${manifestPath}: ${err.message}`,
        exitCode: 2,
      }),
      options,
      2,
    );
  }

  const result: ValidationResult = parseAndValidate(content);

  if (!result.valid) {
    let exitCode = 2; // Default manifest/schema error
    if (result.required_approvals && result.required_approvals.length > 0) {
      exitCode = 4; // Approval required
    }

    if (options.json) {
      console.log(JSON.stringify(result, null, 2));
      process.exit(exitCode);
    } else {
      console.error("\x1b[31mManifest validation failed:\x1b[0m");
      for (const err of result.errors) {
        console.error(`  - \x1b[1m[${err.code}]\x1b[0m ${err.message}`);
        if (err.path) console.error(`    Field: ${err.path}`);
        if (err.hint) console.error(`    Hint:  \x1b[36m${err.hint}\x1b[0m`);
      }
      process.exit(exitCode);
    }
  }

  // Valid
  outputResult(result, options, () => {
    console.log("\x1b[32m✔ Manifest is valid!\x1b[0m");
    if (result.warnings && result.warnings.length > 0) {
      console.log("\nWarnings:");
      for (const w of result.warnings) {
        console.log(`  - ${w.message}`);
      }
    }
  });
}
