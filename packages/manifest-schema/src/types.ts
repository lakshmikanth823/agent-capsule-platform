/**
 * Type definitions for Software Capsule Manifest and Validation Engine.
 * Conforms to docs/manifest-spec/ and docs/api-cli-spec/
 */

export interface ConnectorDeclaration {
  name: string;
  channel?: string;
  acts_as: 'viewer' | 'service';
  spreadsheet_ids?: string[];
}

export interface ManifestCapabilities {
  db?: {
    type: 'sqlite';
  };
  identity?: boolean;
  files?: {
    max_mb: number;
  };
  ai?: {
    monthly_budget_usd: number;
    model?: string;
    models?: string[];
  };
  connectors?: ConnectorDeclaration[];
}

export interface ManifestSchedule {
  cron: string;
  handler: string;
}

export interface ManifestSharing {
  default: 'org';
}

export interface ManifestLimits {
  cpu?: 'small';
  memory_mb?: number;
  request_timeout_s?: number;
  db_max_mb?: number;
  blob_max_mb?: number;
  max_active_instances?: 1;
}

export interface CapsuleManifest {
  apiVersion: 'capsule/v1alpha1';
  id: string;
  name: string;
  shape: 'web-app';
  runtime: 'node22';
  roles?: string[];
  capabilities?: ManifestCapabilities;
  egress?: string[];
  schedule?: ManifestSchedule[];
  sharing?: ManifestSharing;
  limits?: ManifestLimits;
}

export interface ValidationCheck {
  name: string;
  status: 'pass' | 'fail' | 'warn';
  code: string;
  message: string;
  path?: string | null;
  hint?: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationCheck[];
  checks: ValidationCheck[];
  required_approvals: string[];
  warnings: ValidationCheck[];
  effective_manifest?: CapsuleManifest;
}
