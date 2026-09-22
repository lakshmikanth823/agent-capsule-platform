/**
 * CLI Configuration Management
 * Stores session tokens and API URLs in ~/.capsule/config.json.
 */
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

export interface CliConfig {
  apiUrl: string;
  token?: string;
  user?: {
    id: string;
    email: string;
    displayName?: string;
  };
  org?: {
    id: string;
    slug: string;
    name?: string;
  };
}

function getConfigDir(): string {
  if (process.env.CAPSULE_CONFIG_DIR) {
    return path.resolve(process.env.CAPSULE_CONFIG_DIR);
  }
  return path.join(os.homedir(), ".capsule");
}

function getConfigPath(): string {
  return path.join(getConfigDir(), "config.json");
}

export function loadConfig(): CliConfig {
  const configPath = getConfigPath();
  const defaultApiUrl =
    process.env.CONTROL_PLANE_URL || "http://localhost:8000";
  const envToken = process.env.CAPSULE_TOKEN || process.env.CAPSULE_API_KEY;

  if (!fs.existsSync(configPath)) {
    return {
      apiUrl: defaultApiUrl,
      token: envToken,
    };
  }

  try {
    const raw = fs.readFileSync(configPath, "utf8");
    const parsed = JSON.parse(raw);
    return {
      apiUrl: process.env.CONTROL_PLANE_URL || parsed.apiUrl || defaultApiUrl,
      token: envToken || parsed.token,
      user: parsed.user,
      org: parsed.org,
    };
  } catch {
    return {
      apiUrl: defaultApiUrl,
      token: envToken,
    };
  }
}

export function saveConfig(updates: Partial<CliConfig>): CliConfig {
  const current = loadConfig();
  const merged: CliConfig = {
    ...current,
    ...updates,
  };

  const dir = getConfigDir();
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  fs.writeFileSync(getConfigPath(), JSON.stringify(merged, null, 2), "utf8");
  return merged;
}

export function clearConfig(): void {
  const configPath = getConfigPath();
  if (fs.existsSync(configPath)) {
    fs.unlinkSync(configPath);
  }
}
