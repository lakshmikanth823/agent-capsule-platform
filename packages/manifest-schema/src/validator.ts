/**
 * Pure validation engine for Software Capsule Manifests.
 * Implements syntax, schema, and semantic checks per docs/manifest-spec/ and docs/api-cli-spec/.
 */
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import schemaJson from "../schema/capsule.manifest.schema.json" with { type: "json" };
import type {
  CapsuleManifest,
  ValidationCheck,
  ValidationResult,
  ConnectorDeclaration,
} from "./types.js";

// Handle CJS/ESM interop under NodeNext module resolution
const Ajv2020Constructor: any = (Ajv2020 as any).default || Ajv2020;
const addFormatsFn: any = (addFormats as any).default || addFormats;

const ajv = new Ajv2020Constructor({ allErrors: true, strict: false });
addFormatsFn(ajv);
const validateSchema = ajv.compile(schemaJson);

const HOSTNAME_REGEX =
  /^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$/;
const IP_REGEX =
  /^(?:\d{1,3}\.){3}\d{1,3}$|^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$/;
const ID_REGEX = /^[a-z0-9][a-z0-9-]{0,62}$/;
const ROLE_REGEX = /^[a-z][a-z0-9_-]{0,31}$/;

export function validateManifest(input: unknown): ValidationResult {
  const checks: ValidationCheck[] = [];
  const requiredApprovals: string[] = [];

  // 1. Basic Type Check
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    const check: ValidationCheck = {
      name: "input_format",
      status: "fail",
      code: "invalid_manifest",
      path: null,
      message: "Manifest must be a non-null object.",
      hint: "Provide a valid YAML/JSON document with top-level fields: apiVersion, id, name, shape, runtime.",
    };
    return {
      valid: false,
      errors: [check],
      checks: [check],
      required_approvals: [],
      warnings: [],
    };
  }

  const manifest = input as Record<string, any>;

  // 2. Schema Validation (Draft 2020-12)
  const isSchemaValid = validateSchema(manifest);
  if (!isSchemaValid && validateSchema.errors) {
    for (const err of validateSchema.errors) {
      let path = err.instancePath
        ? err.instancePath.replace(/^\//, "").replace(/\//g, ".")
        : null;
      let message = err.message || "Schema validation error";
      let hint = "Fix the field according to capsule.manifest.schema.json.";

      if (err.keyword === "required") {
        const missing = (err.params as any).missingProperty;
        path = path ? `${path}.${missing}` : missing;
        message = `Missing required property '${missing}'.`;
        hint = `Add the required '${missing}' property to your manifest.`;
      } else if (err.keyword === "additionalProperties") {
        const extra = (err.params as any).additionalProperty;
        path = path ? `${path}.${extra}` : extra;
        message = `Unrecognized property '${extra}'.`;
        hint = `Remove '${extra}'. Unknown properties are not permitted.`;
      } else if (err.keyword === "const") {
        const expected = (err.params as any).allowedValue;
        message = `Value must be '${expected}'.`;
        hint = `Change value to '${expected}'.`;
      } else if (err.keyword === "pattern") {
        if (path === "id") {
          message = `Invalid capsule ID '${manifest.id}'.`;
          hint =
            "Capsule ID must be 1-63 lowercase alphanumeric characters and hyphens (e.g. leave-tracker).";
        } else if (path?.startsWith("roles")) {
          message = `Invalid role name format.`;
          hint =
            "Role names must start with lowercase letter and use snake_case (e.g. hr_manager).";
        } else {
          message = `Value at '${path}' does not match required pattern.`;
          hint = `Ensure '${path}' conforms to pattern: ${(err.params as any).pattern}`;
        }
      }

      checks.push({
        name: "schema_validation",
        status: "fail",
        code: "invalid_manifest",
        path,
        message,
        hint,
      });
    }
  } else {
    checks.push({
      name: "schema_validation",
      status: "pass",
      code: "schema_valid",
      message: "Manifest conforms to JSON Schema Draft 2020-12.",
      path: null,
    });
  }

  // 3. Semantic Checks: Shape
  if (manifest.shape !== undefined) {
    if (manifest.shape !== "web-app") {
      checks.push({
        name: "shape_check",
        status: "fail",
        code: "unsupported_shape",
        path: "shape",
        message: `Unsupported shape '${manifest.shape}'.`,
        hint: "Set 'shape' to 'web-app'. Only web-app is supported in Alpha/MVP.",
      });
    } else {
      checks.push({
        name: "shape_check",
        status: "pass",
        code: "shape_valid",
        message: "Shape 'web-app' is valid.",
        path: "shape",
      });
    }
  }

  // 4. Semantic Checks: Runtime
  if (manifest.runtime !== undefined) {
    if (manifest.runtime !== "node22") {
      checks.push({
        name: "runtime_check",
        status: "fail",
        code: "unsupported_runtime",
        path: "runtime",
        message: `Unsupported runtime '${manifest.runtime}'.`,
        hint: "Set 'runtime' to 'node22'. Only node22 is supported in Alpha/MVP.",
      });
    } else {
      checks.push({
        name: "runtime_check",
        status: "pass",
        code: "runtime_valid",
        message: "Runtime 'node22' is valid.",
        path: "runtime",
      });
    }
  }

  // 5. Semantic Checks: ID Format
  if (manifest.id !== undefined && typeof manifest.id === "string") {
    if (!ID_REGEX.test(manifest.id)) {
      checks.push({
        name: "id_check",
        status: "fail",
        code: "invalid_manifest",
        path: "id",
        message: `Invalid capsule ID '${manifest.id}'.`,
        hint: "Capsule ID must be 1-63 lowercase alphanumeric characters and hyphens (e.g. leave-tracker).",
      });
    } else {
      checks.push({
        name: "id_check",
        status: "pass",
        code: "id_valid",
        message: "Capsule ID format is valid.",
        path: "id",
      });
    }
  }

  // 6. Semantic Checks: Roles Uniqueness & Format
  if (Array.isArray(manifest.roles)) {
    const seenRoles = new Set<string>();
    for (let i = 0; i < manifest.roles.length; i++) {
      const role = manifest.roles[i];
      if (typeof role === "string") {
        if (!ROLE_REGEX.test(role)) {
          checks.push({
            name: "roles_check",
            status: "fail",
            code: "invalid_manifest",
            path: `roles[${i}]`,
            message: `Invalid role format '${role}'.`,
            hint: "Roles must start with a letter and contain only lowercase letters, digits, underscores, or hyphens (max 32 chars).",
          });
        }
        if (seenRoles.has(role)) {
          checks.push({
            name: "roles_check",
            status: "fail",
            code: "invalid_manifest",
            path: `roles[${i}]`,
            message: `Duplicate role '${role}'.`,
            hint: "Remove duplicate role declarations.",
          });
        }
        seenRoles.add(role);
      }
    }
  }

  // 7. Semantic Checks: Network Egress & Default-Deny
  const egressList = manifest.egress !== undefined ? manifest.egress : [];
  if (Array.isArray(egressList)) {
    if (egressList.length === 0) {
      checks.push({
        name: "egress_check",
        status: "pass",
        code: "egress_default_deny",
        message: "Default-deny egress policy is active.",
        path: "egress",
      });
    } else {
      for (let i = 0; i < egressList.length; i++) {
        const dest = egressList[i];
        if (typeof dest !== "string") continue;

        // Check for URL scheme
        if (dest.includes("://") || dest.includes("/")) {
          checks.push({
            name: "egress_check",
            status: "fail",
            code: "egress_denied",
            path: `egress[${i}]`,
            message: `Egress destination '${dest}' contains a URL scheme or path.`,
            hint: "Specify only the FQDN hostname (e.g. api.example.com). Protocols, ports, and paths are not allowed.",
          });
          continue;
        }

        // Check for port
        if (dest.includes(":")) {
          checks.push({
            name: "egress_check",
            status: "fail",
            code: "egress_denied",
            path: `egress[${i}]`,
            message: `Egress destination '${dest}' contains a port number.`,
            hint: "Specify only the FQDN hostname without port.",
          });
          continue;
        }

        // Check for direct IP address
        if (IP_REGEX.test(dest)) {
          checks.push({
            name: "egress_check",
            status: "fail",
            code: "egress_denied",
            path: `egress[${i}]`,
            message: `Direct IP address destination '${dest}' is prohibited.`,
            hint: "Specify an approved external domain hostname instead of a raw IP address.",
          });
          continue;
        }

        // Check for loopback / local
        const lower = dest.toLowerCase();
        if (
          lower === "localhost" ||
          lower.endsWith(".localhost") ||
          lower === "metadata.google.internal"
        ) {
          checks.push({
            name: "egress_check",
            status: "fail",
            code: "egress_denied",
            path: `egress[${i}]`,
            message: `Loopback or metadata destination '${dest}' is prohibited.`,
            hint: "Loopback and internal cloud metadata addresses cannot be declared as egress destinations.",
          });
          continue;
        }

        // Validate hostname syntax
        if (!HOSTNAME_REGEX.test(dest)) {
          checks.push({
            name: "egress_check",
            status: "fail",
            code: "egress_denied",
            path: `egress[${i}]`,
            message: `Egress destination '${dest}' is not a valid hostname.`,
            hint: "Provide a valid fully qualified domain name (e.g. api.slack.com).",
          });
          continue;
        }

        checks.push({
          name: "egress_check",
          status: "pass",
          code: "egress_allowed",
          message: `Egress destination '${dest}' passed hostname validation.`,
          path: `egress[${i}]`,
        });
      }
    }
  }

  // 8. Semantic Checks: Resource Limits
  if (manifest.limits && typeof manifest.limits === "object") {
    const limits = manifest.limits;
    if (
      limits.memory_mb !== undefined &&
      (limits.memory_mb < 64 || limits.memory_mb > 16384)
    ) {
      checks.push({
        name: "limits_check",
        status: "fail",
        code: "quota_exceeded",
        path: "limits.memory_mb",
        message: `Requested memory_mb (${limits.memory_mb}) is outside allowed range (64 - 16384 MB).`,
        hint: "Set memory_mb between 64 and 16384 (e.g. 256).",
      });
    }
    if (
      limits.request_timeout_s !== undefined &&
      (limits.request_timeout_s < 1 || limits.request_timeout_s > 300)
    ) {
      checks.push({
        name: "limits_check",
        status: "fail",
        code: "quota_exceeded",
        path: "limits.request_timeout_s",
        message: `Request timeout (${limits.request_timeout_s}s) is outside allowed range (1 - 300 seconds).`,
        hint: "Set request_timeout_s between 1 and 300 (e.g. 30).",
      });
    }
    if (
      limits.max_active_instances !== undefined &&
      limits.max_active_instances !== 1
    ) {
      checks.push({
        name: "limits_check",
        status: "fail",
        code: "quota_exceeded",
        path: "limits.max_active_instances",
        message: `max_active_instances must be 1.`,
        hint: "SQLite write model requires max_active_instances: 1.",
      });
    }
  }

  // 9. Semantic Checks: Capabilities & Connectors Defaults / Approvals
  if (manifest.capabilities && typeof manifest.capabilities === "object") {
    const caps = manifest.capabilities;
    if (caps.db && caps.db.type !== "sqlite") {
      checks.push({
        name: "capabilities_check",
        status: "fail",
        code: "capability_not_allowed",
        path: "capabilities.db.type",
        message: `Database type '${caps.db.type}' is not supported.`,
        hint: "Set capabilities.db.type to 'sqlite'.",
      });
    }

    if (Array.isArray(caps.connectors)) {
      for (let i = 0; i < caps.connectors.length; i++) {
        const conn = caps.connectors[i];
        if (!conn || typeof conn !== "object") continue;

        const actsAs = conn.acts_as || "viewer";
        if (actsAs === "service") {
          const approvalKey = `connectors.${conn.name}:service`;
          requiredApprovals.push(approvalKey);
          checks.push({
            name: "connector_approval",
            status: "warn",
            code: "approval_required",
            path: `capabilities.connectors[${i}].acts_as`,
            message: `Privileged 'service' identity requested for connector '${conn.name}'.`,
            hint: "Service identity requires human owner approval before activation.",
          });
        }
      }
    }
  }

  // 10. Semantic Checks: Schedule (Deferred to Phase 3)
  if (
    manifest.schedule &&
    Array.isArray(manifest.schedule) &&
    manifest.schedule.length > 0
  ) {
    checks.push({
      name: "schedule_check",
      status: "warn",
      code: "unsupported_capability",
      path: "schedule",
      message:
        "Scheduled execution is deferred until Phase 3 and is not active in Alpha.",
      hint: "Remove the 'schedule' field or note that it will remain dormant until Phase 3.",
    });
  }

  // Compile overall status
  const errors = checks.filter((c) => c.status === "fail");
  const warnings = checks.filter((c) => c.status === "warn");
  const valid = errors.length === 0;

  // Compute effective manifest with defaults resolved
  let effectiveManifest: CapsuleManifest | undefined = undefined;
  if (valid) {
    const normalizedConnectors: ConnectorDeclaration[] | undefined = manifest
      .capabilities?.connectors
      ? manifest.capabilities.connectors.map((c: any) => ({
          name: c.name,
          channel: c.channel,
          acts_as: c.acts_as || "viewer",
        }))
      : undefined;

    effectiveManifest = {
      apiVersion: manifest.apiVersion,
      id: manifest.id,
      name: manifest.name,
      shape: manifest.shape,
      runtime: manifest.runtime,
      roles: manifest.roles ? [...manifest.roles] : undefined,
      capabilities: manifest.capabilities
        ? {
            ...manifest.capabilities,
            connectors: normalizedConnectors,
          }
        : undefined,
      egress: manifest.egress ? [...manifest.egress] : [],
      sharing: manifest.sharing || { default: "org" },
      limits: {
        cpu: manifest.limits?.cpu || "small",
        memory_mb: manifest.limits?.memory_mb || 256,
        request_timeout_s: manifest.limits?.request_timeout_s || 30,
        db_max_mb: manifest.limits?.db_max_mb || 500,
        blob_max_mb: manifest.limits?.blob_max_mb || 200,
        max_active_instances: 1,
      },
    };
  }

  return {
    valid,
    errors,
    checks,
    required_approvals: requiredApprovals,
    warnings,
    effective_manifest: effectiveManifest,
  };
}

/**
 * Helper to check if a shape is currently supported.
 */
export function isManifestShapeValid(shape: string): boolean {
  return shape === "web-app";
}

/**
 * Helper to check if a runtime is currently supported.
 */
export function isRuntimeValid(runtime: string): boolean {
  return runtime === "node22";
}
