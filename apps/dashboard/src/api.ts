/**
 * API client for Software Capsule Platform Control Plane
 */
import {
  AppDetail,
  AppShare,
  AppSummary,
  AppVersion,
  AuditEvent,
  UserProfile,
  EnvironmentProfileData,
  ProfileDiffResult,
  InventoryItem,
  InventoryResponse,
  AIUsageSummary,
  AIRequestsResponse,
  AppAIUsage,
} from "./types";

const TOKEN_KEY = "capsule_token";

export function getStoredToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

function getBaseUrl(): string {
  // If served from edge-proxy on platform.localhost:8080 or similar
  if (
    window.location.hostname.includes("platform.localhost") ||
    window.location.port === "8080"
  ) {
    return "/v1";
  }
  // If running standalone Vite dev server
  return "http://localhost:8000/v1";
}

async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const baseUrl = getBaseUrl();
  const token = getStoredToken();

  const headers = new Headers(options.headers || {});
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${baseUrl}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorDetail = "API request failed";
    try {
      const errorJson = await response.json();
      errorDetail =
        errorJson.detail?.message || errorJson.detail || errorDetail;
    } catch {
      errorDetail = `${response.status} ${response.statusText}`;
    }
    throw new Error(errorDetail);
  }

  return response.json();
}

export const api = {
  async getMe(): Promise<UserProfile> {
    return apiFetch<UserProfile>("/auth/me");
  },

  async listApps(): Promise<AppSummary[]> {
    const res = await apiFetch<{ items: AppSummary[] }>("/apps");
    return res.items;
  },

  async getApp(appId: string): Promise<AppDetail> {
    return apiFetch<AppDetail>(`/apps/${appId}`);
  },

  async listVersions(appId: string): Promise<AppVersion[]> {
    const res = await apiFetch<{ items: AppVersion[] }>(
      `/apps/${appId}/versions`,
    );
    return res.items;
  },

  async listShares(appId: string): Promise<{
    shares: AppShare[];
    default_scope: string;
    external_users_allowed: boolean;
  }> {
    return apiFetch<{
      shares: AppShare[];
      default_scope: string;
      external_users_allowed: boolean;
    }>(`/apps/${appId}/shares`);
  },

  async createShare(
    appId: string,
    data: { user_email?: string; group_name?: string; app_role: string },
  ): Promise<AppShare> {
    return apiFetch<AppShare>(`/apps/${appId}/shares`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async revokeShare(appId: string, shareId: string): Promise<void> {
    await apiFetch(`/apps/${appId}/shares/${shareId}`, {
      method: "DELETE",
    });
  },

  async getLogs(
    appId: string,
    tail = 100,
  ): Promise<{ app_id: string; app_key: string; logs: string[] }> {
    return apiFetch<{ app_id: string; app_key: string; logs: string[] }>(
      `/apps/${appId}/logs?tail=${tail}`,
    );
  },

  async listAuditEvents(appId?: string): Promise<AuditEvent[]> {
    const query = appId ? `?app_id=${appId}` : "";
    return apiFetch<AuditEvent[]>(`/audit/events${query}`);
  },

  async listOrgAuditEvents(
    orgId: string,
    params: Record<string, any> = {},
  ): Promise<{
    items: AuditEvent[];
    total: number;
    limit: number;
    offset: number;
  }> {
    const queryParts = Object.entries(params)
      .filter(([_, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
    const query = queryParts.length > 0 ? `?${queryParts.join("&")}` : "";
    return apiFetch<{
      items: AuditEvent[];
      total: number;
      limit: number;
      offset: number;
    }>(`/organizations/${orgId}/audit/events${query}`);
  },

  async getAuditEventDetail(
    orgId: string,
    eventId: string,
  ): Promise<AuditEvent> {
    return apiFetch<AuditEvent>(
      `/organizations/${orgId}/audit/events/${eventId}`,
    );
  },

  async verifyAuditChain(orgId: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/audit/verify`, {
      method: "POST",
    });
  },

  async enforceAuditRetention(orgId: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/audit/retention/enforce`, {
      method: "POST",
    });
  },

  async getAuditWebhook(orgId: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/audit/webhook`);
  },

  async updateAuditWebhook(
    orgId: string,
    data: { url: string; secret_token?: string; is_active?: boolean },
  ): Promise<any> {
    return apiFetch(`/organizations/${orgId}/audit/webhook`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  async deleteAuditWebhook(orgId: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/audit/webhook`, {
      method: "DELETE",
    });
  },

  async testAuditWebhook(orgId: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/audit/webhook/test`, {
      method: "POST",
    });
  },

  async rollbackApp(
    appId: string,
    data: {
      target_version_number?: number;
      target_version_id?: string;
      mode?: "code_only" | "code_and_data";
      confirm_data_restore?: boolean;
      reason?: string;
    },
  ): Promise<any> {
    return apiFetch(`/apps/${appId}/rollback`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async suspendApp(appId: string, reason: string): Promise<any> {
    return apiFetch(`/kill-switch/apps/${appId}/suspend`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  async resumeApp(appId: string): Promise<any> {
    return apiFetch(`/kill-switch/apps/${appId}/resume`, {
      method: "POST",
    });
  },

  async getEnvironmentProfile(orgId: string): Promise<EnvironmentProfileData> {
    return apiFetch<EnvironmentProfileData>(
      `/organizations/${orgId}/environment-profile`,
    );
  },

  async previewProfileDiff(
    orgId: string,
    profile: Record<string, any>,
  ): Promise<ProfileDiffResult> {
    return apiFetch<ProfileDiffResult>(
      `/organizations/${orgId}/environment-profile/preview-diff`,
      {
        method: "POST",
        body: JSON.stringify({ profile }),
      },
    );
  },

  async updateEnvironmentProfile(
    orgId: string,
    profile: Record<string, any>,
  ): Promise<any> {
    return apiFetch(`/organizations/${orgId}/environment-profile`, {
      method: "PUT",
      body: JSON.stringify({ profile }),
    });
  },

  async getEffectivePolicy(appId: string): Promise<any> {
    return apiFetch(`/apps/${appId}/effective-policy`);
  },

  async getIdp(orgId: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/sso/idp`);
  },

  async configureIdp(orgId: string, data: any): Promise<any> {
    return apiFetch(`/organizations/${orgId}/sso/idp`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  async listDomains(orgId: string): Promise<any[]> {
    return apiFetch<any[]>(`/organizations/${orgId}/domains`);
  },

  async claimDomain(orgId: string, domain: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/domains`, {
      method: "POST",
      body: JSON.stringify({ domain }),
    });
  },

  async verifyDomain(orgId: string, domain: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/domains/${domain}/verify`, {
      method: "POST",
    });
  },

  async deleteDomain(orgId: string, domain: string): Promise<void> {
    await apiFetch(`/organizations/${orgId}/domains/${domain}`, {
      method: "DELETE",
    });
  },

  async rotateScimToken(orgId: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/scim/rotate-token`, {
      method: "POST",
    });
  },

  async getScimTokenInfo(orgId: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/scim/token`);
  },

  async listGroupRoleMappings(orgId: string): Promise<any[]> {
    return apiFetch<any[]>(`/organizations/${orgId}/group-role-mappings`);
  },

  async createGroupRoleMapping(
    orgId: string,
    data: { group_id: string; app_id: string; app_role: string },
  ): Promise<any> {
    return apiFetch(`/organizations/${orgId}/group-role-mappings`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async deleteGroupRoleMapping(
    orgId: string,
    mappingId: string,
  ): Promise<void> {
    await apiFetch(`/organizations/${orgId}/group-role-mappings/${mappingId}`, {
      method: "DELETE",
    });
  },

  async getInventory(orgId: string): Promise<InventoryResponse> {
    return apiFetch<InventoryResponse>(`/organizations/${orgId}/inventory`);
  },

  async exportInventoryCsv(orgId: string): Promise<string> {
    const baseUrl = getBaseUrl();
    const token = getStoredToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(
      `${baseUrl}/organizations/${orgId}/inventory/export?format=csv`,
      { headers },
    );
    if (!res.ok) throw new Error("Failed to export CSV");
    return res.text();
  },

  async transferOwnership(
    appId: string,
    newOwnerUserId: string,
    reason: string,
  ): Promise<any> {
    return apiFetch(`/apps/${appId}/transfer-ownership`, {
      method: "POST",
      body: JSON.stringify({ new_owner_user_id: newOwnerUserId, reason }),
    });
  },

  async updateGovernanceSettings(
    appId: string,
    data: {
      nominated_owner_user_id?: string | null;
      expires_at?: string | null;
      inactivity_days_limit?: number | null;
      purge_after_days?: number | null;
    },
  ): Promise<any> {
    return apiFetch(`/apps/${appId}/governance`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async runGovernanceCycle(orgId: string): Promise<any> {
    return apiFetch(`/organizations/${orgId}/governance/run-cycle`, {
      method: "POST",
    });
  },

  async getAppExportData(appId: string): Promise<any> {
    return apiFetch(`/apps/${appId}/export-data`);
  },

  async getOrgAIUsage(
    orgId: string,
    startTime?: string,
    endTime?: string,
  ): Promise<AIUsageSummary> {
    const params = new URLSearchParams();
    if (startTime) params.append("start_time", startTime);
    if (endTime) params.append("end_time", endTime);
    const query = params.toString() ? `?${params.toString()}` : "";
    return apiFetch<AIUsageSummary>(`/organizations/${orgId}/ai/usage${query}`);
  },

  async getOrgAIRequests(
    orgId: string,
    params?: {
      appId?: string;
      model?: string;
      status?: string;
      limit?: number;
      offset?: number;
    },
  ): Promise<AIRequestsResponse> {
    const sp = new URLSearchParams();
    if (params?.appId) sp.append("app_id", params.appId);
    if (params?.model) sp.append("model", params.model);
    if (params?.status) sp.append("status", params.status);
    if (params?.limit) sp.append("limit", String(params.limit));
    if (params?.offset) sp.append("offset", String(params.offset));
    const query = sp.toString() ? `?${sp.toString()}` : "";
    return apiFetch<AIRequestsResponse>(
      `/organizations/${orgId}/ai/requests${query}`,
    );
  },

  async getAppAIUsage(appId: string): Promise<AppAIUsage> {
    return apiFetch<AppAIUsage>(`/apps/${appId}/ai/usage`);
  },

  async purgeExpiredAIContent(
    orgId: string,
    retentionDays?: number,
  ): Promise<any> {
    return apiFetch(`/organizations/${orgId}/ai/purge-content`, {
      method: "POST",
      body: JSON.stringify(
        retentionDays ? { retention_days: retentionDays } : {},
      ),
    });
  },
};
