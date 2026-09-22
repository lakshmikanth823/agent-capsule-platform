/**
 * @capsule/sdk
 * Platform SDK for the blessed Node.js 22 + TypeScript application shape.
 * Provides per-capsule SQLite database, verified identity parsing, and blob storage.
 * Note: The platform, not this SDK, is the security boundary.
 */

import { getDatabase, SQLiteDatabase, type DatabaseClient, type DatabaseOptions, type RunResult } from './db.js';
import {
  getIdentity,
  requireIdentity,
  getEmulatorIdentity,
  createIdentityContext,
  IdentityVerificationError,
  type IdentityContext,
  type VerifyIdentityOptions,
} from './identity.js';
import {
  getFiles,
  PlatformFileStorage,
  FileStorageError,
  type FileStorageClient,
  type FileMetadata,
  type PutFileResult,
  type GetFileResult,
} from './files.js';
import {
  isEmulatorMode,
  createDevIdentityToken,
  setupEmulator,
  type DevTokenOptions,
  type EmulatorConfig,
} from './emulator.js';
import {
  getConnector,
  PlatformConnectorClient,
  ConnectorError,
  type ConnectorClient,
  type ConnectorInvokeOptions,
} from './connectors.js';
import {
  getAI,
  PlatformAIClient,
  AIGatewayError,
  type AIChatMessage,
  type AIChatOptions,
  type AIChatResponse,
  type AIStreamChunk,
  type AppAIUsage,
  type AIUsageMetrics,
} from './ai.js';

export {
  // Database
  getDatabase,
  SQLiteDatabase,
  DatabaseClient,
  DatabaseOptions,
  RunResult,
  // Identity
  getIdentity,
  requireIdentity,
  getEmulatorIdentity,
  IdentityVerificationError,
  IdentityContext,
  VerifyIdentityOptions,
  // Files / Blob storage
  getFiles,
  PlatformFileStorage,
  FileStorageError,
  FileStorageClient,
  FileMetadata,
  PutFileResult,
  GetFileResult,
  // Emulator
  isEmulatorMode,
  createDevIdentityToken,
  setupEmulator,
  DevTokenOptions,
  EmulatorConfig,
  // Connectors
  getConnector,
  PlatformConnectorClient,
  ConnectorError,
  ConnectorClient,
  ConnectorInvokeOptions,
  // AI Gateway
  getAI,
  PlatformAIClient,
  AIGatewayError,
  AIChatMessage,
  AIChatOptions,
  AIChatResponse,
  AIStreamChunk,
  AppAIUsage,
  AIUsageMetrics,
};

/**
 * Backward-compatible helper for parsing identity header.
 * Supports both signed JWT tokens and raw JSON strings.
 */
export function parseIdentityHeader(headerValue?: string): IdentityContext | null {
  if (!headerValue) return null;
  try {
    const parsed = JSON.parse(headerValue);
    if (parsed && typeof parsed === 'object' && typeof parsed.sub === 'string') {
      return createIdentityContext(parsed);
    }
  } catch {
    // Not raw JSON, try getIdentity (JWT)
  }
  return getIdentity(headerValue);
}

/**
 * Unified SDK interface.
 */
export const sdk = {
  get db() {
    return getDatabase();
  },
  get files() {
    return getFiles();
  },
  get ai() {
    return getAI();
  },
  connector: (name: string) => getConnector(name),
  connectors: {
    invoke: (name: string, payload: any, options?: ConnectorInvokeOptions) =>
      getConnector(name).invoke(payload, options),
  },
  getIdentity,
  requireIdentity,
  isEmulatorMode,
  setupEmulator,
  createDevIdentityToken,
  version: '0.1.0',
};

export const sdkVersion = '0.1.0';

export default sdk;
