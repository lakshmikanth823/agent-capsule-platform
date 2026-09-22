/**
 * Capsule Platform Connectors SDK
 *
 * Implements TRD Section 21 & PRD FR-024 / FR-025 / FR-026:
 * - Applications ask the broker for declared connector capabilities.
 * - Credentials are never present in the application's environment, files, or database.
 * - Credentials are attached downstream by the broker at the egress layer.
 * - In local emulator mode, provides safe local emulation without requiring external credentials.
 */

import { isEmulatorMode } from './emulator.js';

export interface ConnectorClient {
  readonly name: string;
  invoke<T = any>(payload: any, options?: ConnectorInvokeOptions): Promise<T>;
}

export interface ConnectorInvokeOptions {
  identityHeader?: string;
  appKey?: string;
  brokerUrl?: string;
}

export interface SheetsReadPayload {
  spreadsheet_id?: string;
  spreadsheetId?: string;
  range?: string;
}

export interface SheetsReadResponse {
  connector: string;
  status: 'success' | 'failed';
  spreadsheet_id: string;
  range: string;
  major_dimension: string;
  values: any[][];
  emulator?: boolean;
}

export class ConnectorError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly connector: string,
    public readonly statusCode: number,
    public readonly details?: any
  ) {
    super(message);
    this.name = 'ConnectorError';
  }
}

export class PlatformConnectorClient implements ConnectorClient {
  constructor(public readonly name: string) {}

  async invoke<T = any>(payload: any, options: ConnectorInvokeOptions = {}): Promise<T> {
    // 1. Local Emulator Mode
    if (isEmulatorMode() && !process.env.CAPSULE_BROKER_URL) {
      return this.emulateLocal<T>(payload);
    }

    // 2. Platform Mode: Invoke Credential Broker via HTTP
    const brokerUrl =
      options.brokerUrl ||
      process.env.CAPSULE_BROKER_URL ||
      process.env.CONTROL_PLANE_URL ||
      'http://localhost:8000';

    const appKey =
      options.appKey ||
      process.env.CAPSULE_KEY ||
      process.env.CAPSULE_ID ||
      'current-app';

    const identityHeader =
      options.identityHeader ||
      process.env.CAPSULE_IDENTITY_TOKEN ||
      '';

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'x-capsule-key': appKey,
    };

    if (identityHeader) {
      headers['x-capsule-identity'] = identityHeader;
    }

    const endpoint = `${brokerUrl.replace(/\/$/, '')}/v1/connectors/${encodeURIComponent(this.name)}/invoke`;

    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload ?? {}),
      });
    } catch (err: any) {
      throw new ConnectorError(
        `Failed to reach credential broker at ${endpoint}: ${err.message}`,
        'BROKER_UNREACHABLE',
        this.name,
        503,
        err
      );
    }

    let responseData: any;
    try {
      responseData = await response.json();
    } catch {
      responseData = { message: await response.text() };
    }

    if (!response.ok) {
      const code = responseData?.detail?.code || responseData?.code || 'CONNECTOR_ERROR';
      const message =
        responseData?.detail?.message ||
        responseData?.message ||
        `Connector '${this.name}' failed with HTTP ${response.status}`;
      throw new ConnectorError(message, code, this.name, response.status, responseData);
    }

    return responseData as T;
  }

  private emulateLocal<T>(payload: any): T {
    if (this.name === 'fake.echo') {
      return {
        connector: 'fake.echo',
        status: 'success',
        echo: payload,
        identity: {
          userId: 'dev-user-001',
          email: 'developer@example.com',
          roles: ['employee', 'manager'],
        },
        credential_attached: true,
        emulator: true,
      } as unknown as T;
    }

    if (this.name === 'slack.post') {
      const channel = payload?.channel || '#dev';
      const text = payload?.text || payload?.message || '';
      return {
        connector: 'slack.post',
        status: 'success',
        ok: true,
        channel,
        ts: `${Date.now() / 1000}`,
        echo_text: text,
        emulator: true,
      } as unknown as T;
    }

    if (this.name === 'sheets.read' || this.name === 'google_sheets.read') {
      const spreadsheetId = payload?.spreadsheet_id || payload?.spreadsheetId || 'sheet-demo-1';
      const range = payload?.range || 'A1:Z100';
      return {
        connector: 'sheets.read',
        status: 'success',
        spreadsheet_id: spreadsheetId,
        range,
        major_dimension: 'ROWS',
        values: [
          ['ID', 'Name', 'Department'],
          ['EMP-01', 'Alice Smith', 'Engineering'],
          ['EMP-02', 'Bob Jones', 'Product'],
        ],
        emulator: true,
      } as unknown as T;
    }

    return {
      connector: this.name,
      status: 'success',
      echo: payload,
      emulator: true,
    } as unknown as T;
  }
}

/**
 * Creates or retrieves a connector client for the given connector name.
 */
export function getConnector(name: string): ConnectorClient {
  return new PlatformConnectorClient(name);
}
