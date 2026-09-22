#!/usr/bin/env node
/**
 * scripts/build.js
 * Cross-platform topological monorepo build script.
 * Ensures packages are compiled in strict dependency order:
 * 1. @capsule/manifest-schema (base types & schema)
 * 2. @capsule/sdk (runtime SDK)
 * 3. @capsule/sandbox-driver (runtime driver)
 * 4. @capsule/cli & @capsule/mcp-server
 * 5. Services & Apps (builder, edge-proxy, egress-proxy, dashboard)
 * 6. Example apps
 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, "..");

const BUILD_ORDER = [
  { name: "@capsule/manifest-schema", dir: "packages/manifest-schema" },
  { name: "@capsule/sdk", dir: "packages/sdk" },
  { name: "@capsule/sandbox-driver", dir: "packages/sandbox-driver" },
  { name: "capsule (cli)", dir: "packages/cli" },
  { name: "@capsule/mcp-server", dir: "packages/mcp-server" },
  { name: "@capsule/builder", dir: "services/builder" },
  { name: "@capsule/edge-proxy", dir: "services/edge-proxy" },
  { name: "@capsule/egress-proxy", dir: "services/egress-proxy" },
  { name: "@capsule/dashboard", dir: "apps/dashboard" },
  { name: "leave-tracker", dir: "examples/leave-tracker" },
  { name: "malicious-app", dir: "examples/malicious-app" },
];

console.log(
  "🚀 Building Agent Capsule Platform monorepo in topological order...\n",
);

for (const pkg of BUILD_ORDER) {
  process.stdout.write(`  📦 Building ${pkg.name} (${pkg.dir})...\n`);
  // Run npm run build via --prefix for cross-platform reliability
  const cmd = `npm run --prefix ${pkg.dir} --if-present build`;
  const result = spawnSync(cmd, {
    cwd: ROOT_DIR,
    shell: true,
    stdio: "inherit",
  });

  if (result.status !== 0) {
    console.error(
      `\n❌ Failed to build ${pkg.name} (exit code ${result.status})`,
    );
    process.exit(result.status || 1);
  }
  console.log(`✅ ${pkg.name} built successfully.\n`);
}

console.log(
  "\n✨ All workspaces built successfully in topological dependency order!",
);
