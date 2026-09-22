/**
 * capsule share
 * Manages capsule sharing and application role assignments.
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

export interface ShareAddOptions {
  role: string;
  user?: string;
  group?: string;
  app?: string;
  expiresAt?: string;
  json?: boolean;
}

export async function shareAddCommand(options: ShareAddOptions): Promise<void> {
  let appKey: string;
  try {
    appKey = resolveAppKey(options.app);
  } catch (err: any) {
    outputError(err, options);
  }

  if (!options.user && !options.group) {
    outputError(
      new CliError({
        code: "MISSING_SHARE_TARGET",
        message: "Must specify either --user <email> or --group <name>.",
        exitCode: 1,
        hint: "Provide --user user@example.com or --group engineering.",
      }),
      options,
    );
  }

  const client = new ApiClient();
  try {
    const result = await client.addShare(appKey, {
      user_email: options.user,
      group_name: options.group,
      app_role: options.role,
      expires_at: options.expiresAt,
    });

    outputResult(
      {
        action: "share_added",
        app: appKey,
        share_id: result.id,
        user: options.user,
        group: options.group,
        role: options.role,
        expires_at: options.expiresAt,
        status: "active",
      },
      options,
      () => {
        const target = options.user
          ? `user ${options.user}`
          : `group ${options.group}`;
        console.log(
          `\x1b[32m✔ Shared ${appKey} with ${target} as role '${options.role}'.\x1b[0m`,
        );
        console.log(`  Share ID: ${result.id}`);
      },
    );
  } catch (err: any) {
    outputError(err, options);
  }
}

export interface ShareListOptions {
  app?: string;
  json?: boolean;
}

export async function shareListCommand(
  options: ShareListOptions = {},
): Promise<void> {
  let appKey: string;
  try {
    appKey = resolveAppKey(options.app);
  } catch (err: any) {
    outputError(err, options);
  }

  const client = new ApiClient();
  try {
    const response = await client.listShares(appKey);
    const shares = response?.shares || [];

    outputResult(
      {
        app: appKey,
        shares,
        default_scope: response?.default_scope || "org",
      },
      options,
      () => {
        console.log(`\x1b[1mShares for ${appKey}:\x1b[0m`);
        if (shares.length === 0) {
          console.log(
            "  (No active individual/group shares. Default org policy applies.)",
          );
          return;
        }
        for (const s of shares) {
          const target = s.user_email
            ? `User: ${s.user_email}`
            : `Group: ${s.group_name}`;
          console.log(
            `  - [${s.id}] ${target} -> Role: '${s.app_role}' (${s.status})`,
          );
        }
      },
    );
  } catch (err: any) {
    outputError(err, options);
  }
}

export interface ShareRevokeOptions {
  app?: string;
  json?: boolean;
}

export async function shareRevokeCommand(
  shareId: string,
  options: ShareRevokeOptions = {},
): Promise<void> {
  let appKey: string;
  try {
    appKey = resolveAppKey(options.app);
  } catch (err: any) {
    outputError(err, options);
  }

  const client = new ApiClient();
  try {
    await client.revokeShare(appKey, shareId);

    outputResult(
      {
        action: "share_revoked",
        app: appKey,
        share_id: shareId,
        status: "revoked",
      },
      options,
      () => {
        console.log(`\x1b[32m✔ Revoked share ${shareId} for ${appKey}.\x1b[0m`);
      },
    );
  } catch (err: any) {
    outputError(err, options);
  }
}
