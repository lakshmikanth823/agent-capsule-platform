/**
 * Core types for Software Capsule Platform Dashboard
 */

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  organization_id: string;
  platform_role: 'owner' | 'editor' | 'user';
  token_type: string;
}

export interface AppSummary {
  id: string;
  organization_id: string;
  owner_user_id: string;
  app_key: string;
  name: string;
  description?: string;
  status: 'draft' | 'active' | 'suspended' | 'archived';
  shape: string;
  runtime: string;
  current_version_id?: string;
  app_url?: string;
  created_at: string;
  updated_at: string;
}

export interface AppDetail extends AppSummary {
  manifest?: {
    schema_version?: string;
    id: string;
    name?: string;
    version?: string;
    runtime?: string;
    roles?: string[];
    capabilities?: {
      db?: { type?: string; size_limit_mb?: number };
      files?: { size_limit_mb?: number };
      network?: { egress?: string[] };
      connectors?: Record<string, any>;
      ai?: { model?: string; monthly_budget_usd?: number };
      identity?: boolean;
    };
    limits?: {
      memory_mb?: number;
      cpu_cores?: number;
      timeout_seconds?: number;
    };
  };
}

export interface AppVersion {
  id: string;
  app_id: string;
  version_number: number;
  status: string;
  source_artifact_ref?: string;
  build_artifact_ref?: string;
  manifest: Record<string, any>;
  db_snapshot_ref?: string;
  publisher_user_id: string;
  publisher_agent?: string;
  change_description?: string;
  published_at: string;
  created_at: string;
}

export interface AppShare {
  id: string;
  app_id: string;
  user_id?: string;
  user_email?: string;
  group_name?: string;
  grant_type: 'user' | 'group';
  app_role: string;
  status: 'active' | 'revoked';
  granted_by_user_id?: string;
  granted_at: string;
  expires_at?: string;
  metadata?: Record<string, any>;
}

export interface AuditEvent {
  id: string;
  action: string;
  outcome: string;
  organization_id?: string;
  app_id?: string;
  actor_user_id?: string;
  target_type: string;
  target_id?: string;
  metadata?: Record<string, any>;
  occurred_at: string;
}
