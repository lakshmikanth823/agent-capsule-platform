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
  publisher_user_id?: string;
  publisher_agent?: string;
  publisher_name?: string;
  change_description?: string;
  published_at?: string;
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
  sequence_number?: number;
  prev_hash?: string;
  event_hash?: string;
  action: string;
  outcome: string;
  organization_id?: string;
  app_id?: string;
  actor_user_id?: string;
  actor_agent?: string;
  actor_tool?: string;
  target_type?: string;
  target_id?: string;
  ip_address?: string;
  user_agent?: string;
  metadata?: Record<string, any>;
  occurred_at: string;
}

export interface EnvironmentProfileData {
  organization_id: string;
  organization_slug: string;
  version: string;
  profile: Record<string, any>;
  raw_profile: Record<string, any>;
}

export interface PolicyViolation {
  code: string;
  error: string;
  field: string;
  rule?: string;
  message: string;
  hint?: string;
}

export interface ProfileDiffResult {
  organization_id: string;
  diff: {
    has_changes: boolean;
    added: Record<string, any>;
    modified: Record<string, any>;
    removed: Record<string, any>;
  };
  impacted_apps: Array<{
    app_id: string;
    app_key: string;
    name: string;
    status: string;
    violations: PolicyViolation[];
    violations_count: number;
  }>;
  impacted_apps_count: number;
  total_apps_evaluated: number;
}

export interface InventoryItem {
  id: string;
  app_key: string;
  name: string;
  description?: string;
  status: string;
  governance_state: string;
  expiry_status: string;
  owner?: {
    id: string;
    email: string;
    display_name: string;
  } | null;
  nominated_owner?: {
    id: string;
    email: string;
    display_name?: string;
  } | null;
  user_count: number;
  capabilities: string[];
  connectors: string[];
  current_version: string;
  last_activity_at?: string | null;
  expires_at?: string | null;
  governance_deadline?: string | null;
  created_at?: string | null;
}

export interface InventoryResponse {
  organization_id: string;
  items: InventoryItem[];
  total: number;
}

export interface AIUsageSummary {
  total_requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_estimated_cost_usd: number;
  by_model: Array<{
    model: string;
    requests: number;
    tokens: number;
    cost_usd: number;
  }>;
  by_app: Array<{
    app_id: string;
    app_name: string;
    requests: number;
    tokens: number;
    cost_usd: number;
  }>;
  by_user: Array<{
    user_id: string | null;
    user_email: string;
    requests: number;
    tokens: number;
    cost_usd: number;
  }>;
}

export interface AIRequestRecord {
  id: string;
  app_id: string;
  user_id: string | null;
  model: string;
  provider: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  duration_ms: number;
  status: string;
  redacted: boolean;
  has_content: boolean;
  created_at: string;
}

export interface AIRequestsResponse {
  items: AIRequestRecord[];
  total: number;
  limit: number;
  offset: number;
}

export interface AppAIUsage {
  app_id: string;
  app_key: string;
  monthly_budget_usd: number;
  current_spend_usd: number;
  remaining_budget_usd: number;
  budget_used_percentage: number;
  monthly_tokens: number;
  monthly_requests: number;
  recent_requests: Array<{
    id: string;
    model: string;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    estimated_cost_usd: number;
    duration_ms: number;
    status: string;
    created_at: string;
  }>;
}


