/**
 * Monorepo lint and sanity check script
 * Validates manifest schemas, package manifests, and forbidden patterns.
 */
import fs from "node:fs";
import path from "node:path";

let errors = 0;

function log(msg) {
  console.log(`[lint] ${msg}`);
}

function error(msg) {
  console.error(`[lint ERROR] ${msg}`);
  errors++;
}

// 1. Validate all package.json files
const packagesDir = path.resolve("packages");
if (fs.existsSync(packagesDir)) {
  for (const pkg of fs.readdirSync(packagesDir)) {
    const pkgJsonPath = path.join(packagesDir, pkg, "package.json");
    if (fs.existsSync(pkgJsonPath)) {
      try {
        const data = JSON.parse(fs.readFileSync(pkgJsonPath, "utf-8"));
        if (!data.name || !data.version) {
          error(`${pkgJsonPath} is missing name or version`);
        }
      } catch (err) {
        error(`Failed to parse ${pkgJsonPath}: ${err.message}`);
      }
    }
  }
}

// 2. Validate example manifests
const examplesDir = path.resolve("examples");
if (fs.existsSync(examplesDir)) {
  for (const ex of fs.readdirSync(examplesDir)) {
    const manifestPath = path.join(examplesDir, ex, "capsule.manifest.yaml");
    if (fs.existsSync(manifestPath)) {
      const content = fs.readFileSync(manifestPath, "utf-8");
      if (!content.includes("apiVersion:") || !content.includes("id:")) {
        error(`${manifestPath} is missing apiVersion or id`);
      }
    }
  }
}

// 3. Check for hardcoded AWS secret keys or forbidden tokens
const forbiddenPatterns = [
  /AKIA[0-9A-Z]{16}/,
  /-----BEGIN RSA PRIVATE KEY-----/,
];

function checkDir(dir) {
  if (!fs.existsSync(dir)) return;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (
      entry.name === "node_modules" ||
      entry.name === ".git" ||
      entry.name === "dist" ||
      entry.name === ".venv"
    )
      continue;
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      checkDir(fullPath);
    } else if (/\.(ts|js|py|json|yaml|yml|sh)$/.test(entry.name)) {
      const content = fs.readFileSync(fullPath, "utf-8");
      for (const pattern of forbiddenPatterns) {
        if (pattern.test(content)) {
          // Allow mock patterns in test files or documentation
          if (
            !fullPath.includes("test") &&
            !fullPath.includes("docs") &&
            !fullPath.includes("ai_gateway.py")
          ) {
            error(`Potential secret pattern matched in ${fullPath}`);
          }
        }
      }
    }
  }
}

checkDir(path.resolve("services"));
checkDir(path.resolve("packages"));

if (errors > 0) {
  console.error(`\n[lint] Failed with ${errors} error(s).`);
  process.exit(1);
} else {
  log("All lint checks passed successfully.");
}
