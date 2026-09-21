/**
 * @capsule/manifest-schema
 * Shared manifest schema and validation definitions.
 */

export interface CapsuleManifest {
  apiVersion: 'capsule/v1alpha1';
  id: string;
  name: string;
  shape: 'web-app';
  runtime: 'node22';
  roles?: string[];
  capabilities?: {
    db?: { type: 'sqlite' };
    identity?: boolean;
    files?: { max_mb: number };
    ai?: { monthly_budget_usd: number };
    connectors?: Array<{
      name: string;
      channel?: string;
      acts_as: 'viewer' | 'service';
    }>;
  };
  egress?: string[];
  schedule?: Array<{
    cron: string;
    handler: string;
  }>;
  sharing?: {
    default: 'org';
  };
  limits?: {
    cpu?: 'small';
    memory_mb?: number;
    request_timeout_s?: number;
    db_max_mb?: number;
    blob_max_mb?: number;
    max_active_instances?: 1;
  };
}

export function isManifestShapeValid(shape: string): shape is 'web-app' {
  return shape === 'web-app';
}

export function isRuntimeValid(runtime: string): runtime is 'node22' {
  return runtime === 'node22';
}
