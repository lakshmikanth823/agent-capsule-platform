/**
 * CLI Control-Plane API Client
 */
import { loadConfig, type CliConfig } from './config.js';
import { CliError } from './errors.js';

export interface RequestOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: any;
  token?: string;
  idempotencyKey?: string;
}

export class ApiClient {
  private config: CliConfig;

  constructor(customConfig?: CliConfig) {
    this.config = customConfig || loadConfig();
  }

  get apiUrl(): string {
    return this.config.apiUrl;
  }

  get token(): string | undefined {
    return this.config.token;
  }

  async request<T = any>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const url = `${this.apiUrl.replace(/\/$/, '')}${endpoint}`;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...options.headers,
    };

    const authToken = options.token || this.token;
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }

    if (options.idempotencyKey) {
      headers['Idempotency-Key'] = options.idempotencyKey;
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method: options.method || 'GET',
        headers,
        body: options.body ? JSON.stringify(options.body) : undefined,
      });
    } catch (err: any) {
      throw new CliError({
        code: 'PLATFORM_NETWORK_ERROR',
        message: `Failed to connect to control-plane at ${this.apiUrl}: ${err.message || err}`,
        exitCode: 10,
        hint: 'Ensure control-plane service is running on the configured apiUrl.',
      });
    }

    if (response.status === 204) {
      return null as T;
    }

    let data: any;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      const status = response.status;
      const detail = data?.detail;
      const message = typeof detail === 'string' ? detail : detail?.message || `HTTP ${status} ${response.statusText}`;
      const code = detail?.code || (status === 401 ? 'UNAUTHORIZED' : status === 403 ? 'FORBIDDEN' : status === 404 ? 'NOT_FOUND' : status === 409 ? 'CONFLICT' : 'API_ERROR');
      const hint = detail?.hint || (status === 401 ? 'Run `capsule login` to authenticate.' : undefined);

      let exitCode = 1;
      if (status === 401 || status === 403) exitCode = 5;
      else if (status === 400 || status === 422) exitCode = 2;
      else if (status === 409) exitCode = 2;
      else if (status >= 500) exitCode = 10;

      throw new CliError({
        code,
        message,
        exitCode,
        field: detail?.field,
        hint,
        details: data,
      });
    }

    return data as T;
  }

  // Auth
  async verifyAuth(token: string): Promise<any> {
    return this.request('/v1/auth/status', { token });
  }

  // Apps
  async getApp(appIdOrKey: string): Promise<any> {
    return this.request(`/v1/apps/${appIdOrKey}`);
  }

  async listApps(): Promise<any[]> {
    return this.request('/v1/apps');
  }

  async createApp(payload: { id: string; name: string; manifest: any }): Promise<any> {
    return this.request('/v1/apps', {
      method: 'POST',
      body: payload,
    });
  }

  // Publish
  async publish(
    appIdOrKey: string,
    payload: {
      manifest: any;
      bundle_tar_gz?: string;
      description?: string;
      expected_version?: number;
    },
    options: { idempotencyKey?: string } = {}
  ): Promise<any> {
    return this.request(`/v1/apps/${appIdOrKey}/publish`, {
      method: 'POST',
      body: payload,
      idempotencyKey: options.idempotencyKey,
    });
  }

  // Versions
  async listVersions(appIdOrKey: string): Promise<any[]> {
    return this.request(`/v1/apps/${appIdOrKey}/versions`);
  }

  // Shares
  async listShares(appIdOrKey: string): Promise<any> {
    return this.request(`/v1/apps/${appIdOrKey}/shares`);
  }

  async addShare(
    appIdOrKey: string,
    payload: {
      user_email?: string;
      user_id?: string;
      group_name?: string;
      app_role: string;
      expires_at?: string;
    }
  ): Promise<any> {
    return this.request(`/v1/apps/${appIdOrKey}/shares`, {
      method: 'POST',
      body: payload,
    });
  }

  async revokeShare(appIdOrKey: string, shareId: string): Promise<void> {
    await this.request(`/v1/apps/${appIdOrKey}/shares/${shareId}`, {
      method: 'DELETE',
    });
  }
}
