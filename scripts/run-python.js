#!/usr/bin/env node
/**
 * scripts/run-python.js
 * Cross-platform runner for Python commands (pytest, alembic, uvicorn, scripts).
 * Automatically detects virtual environments (.venv/bin/python on Linux/Mac,
 * .venv/Scripts/python.exe on Windows) or falls back to system python.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, "..");

function resolvePythonBinary() {
  const isWindows = process.platform === "win32";
  const venvWin = path.join(ROOT_DIR, ".venv", "Scripts", "python.exe");
  const venvPosix = path.join(ROOT_DIR, ".venv", "bin", "python");

  if (isWindows && fs.existsSync(venvWin)) {
    return venvWin;
  }
  if (!isWindows && fs.existsSync(venvPosix)) {
    return venvPosix;
  }
  if (fs.existsSync(venvPosix)) {
    return venvPosix;
  }
  if (fs.existsSync(venvWin)) {
    return venvWin;
  }

  // Fallback to system python
  return isWindows ? "python" : "python3";
}

const pythonBin = resolvePythonBinary();
const args = process.argv.slice(2);

if (args.length === 0) {
  console.error("Usage: node scripts/run-python.js <args...>");
  process.exit(1);
}

const result = spawnSync(pythonBin, args, {
  cwd: ROOT_DIR,
  stdio: "inherit",
  shell: false,
  env: {
    ...process.env,
    PYTHONUNBUFFERED: "1",
  },
});

process.exit(result.status ?? 0);
