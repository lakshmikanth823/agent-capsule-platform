/**
 * API client for Software Capsule Platform Control Plane
 */
import { AppDetail, AppShare, AppSummary, AppVersion, AuditEvent, UserProfile } from './types';

const TOKEN_KEY = 'capsule_token';

export function getStoredToken(): string {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

function getBaseUrl(): string {
  // If served from edge-proxy on platform.localhost:8080 or similar
  if (window.location.hostname.includes('platform.localhost') || window.location.port === '8080') {
    return '/v1';
  }
  // If running standalone Vite dev server
  return 'http://localhost:8000/v1';
}

async function apiFetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const baseUrl = getBaseUrl();
  const token = getStoredToken();

  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${baseUrl}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorDetail = 'API request failed';
    try {
      const errorJson = await response.json();
      errorDetail = errorJson.detail?.message || errorJson.detail || errorDetail;
    } catch {
      errorDetail = `${response.status} ${response.statusText}`;
    }
    throw new Error(errorDetail);
  }

  return response.json();
}

export const api = {
  async getMe(): Promise<UserProfile> {
    return apiFetch<UserProfile>('/auth/me');
  },

  async listApps(): Promise<AppSummary[]> {
    const res = await apiFetch<{ items: AppSummary[] }>('/apps');
    return res.items;
  },

  async getApp(appId: string): Promise<AppDetail> {
    return apiFetch<AppDetail>(`/apps/${appId}`);
  },

  async listVersions(appId: string): Promise<AppVersion[]> {
    const res = await apiFetch<{ items: AppVersion[] }>(`/apps/${appId}/versions`);
    return res.items;
  },

  async listShares(appId: string): Promise<{ shares: AppShare[]; default_scope: string; external_users_allowed: boolean }> {
    return apiFetch<{ shares: AppShare[]; default_scope: string; external_users_allowed: boolean }>(`/apps/${appId}/shares`);
  },

  async createShare(appId: string, data: { user_email?: string; group_name?: string; app_role: string }): Promise<AppShare> {
    return apiFetch<AppShare>(`/apps/${appId}/shares`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async revokeShare(appId: string, shareId: string): Promise<void> {
    await apiFetch(`/apps/${appId}/shares/${shareId}`, {
      method: 'DELETE',
    });
  },

  async getLogs(appId: string, tail = 100): Promise<{ app_id: string; app_key: string; logs: string[] }> {
    return apiFetch<{ app_id: string; app_key: string; logs: string[] }>(`/apps/${appId}/logs?tail=${tail}`);
  },

  async listAuditEvents(appId?: string): Promise<AuditEvent[]> {
    const query = appId ? `?app_id=${appId}` : '';
    return apiFetch<AuditEvent[]>(`/audit/events${query}`);
  },
};
