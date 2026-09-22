/**
 * YAML / JSON Manifest Parser & Validator
 */
import YAML from "yaml";
import { validateManifest } from "./validator.js";
import type { ValidationResult, ValidationCheck } from "./types.js";

export function parseAndValidate(yamlOrJson: string): ValidationResult {
  if (typeof yamlOrJson !== "string" || !yamlOrJson.trim()) {
    const check: ValidationCheck = {
      name: "syntax_validation",
      status: "fail",
      code: "invalid_manifest",
      path: null,
      message: "Manifest input is empty or not a string.",
      hint: "Provide a non-empty YAML or JSON string containing the capsule manifest.",
    };
    return {
      valid: false,
      errors: [check],
      checks: [check],
      required_approvals: [],
      warnings: [],
    };
  }

  let parsed: unknown;
  try {
    parsed = YAML.parse(yamlOrJson);
  } catch (err: any) {
    const check: ValidationCheck = {
      name: "syntax_validation",
      status: "fail",
      code: "invalid_manifest",
      path: null,
      message: `Failed to parse YAML/JSON: ${err?.message || "Syntax error"}`,
      hint: "Check YAML indentation, syntax, and formatting.",
    };
    return {
      valid: false,
      errors: [check],
      checks: [check],
      required_approvals: [],
      warnings: [],
    };
  }

  return validateManifest(parsed);
}
