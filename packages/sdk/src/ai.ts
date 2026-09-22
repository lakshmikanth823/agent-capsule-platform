/**
 * Capsule Platform AI Gateway SDK
 *
 * Implements Prompt 24 & FR-018:
 * - Capsules call AI only through this SDK and platform endpoint.
 * - Provider API keys live in the platform and are never given to apps.
 * - Handles non-streaming and Server-Sent Events (SSE) streaming.
 * - In local emulator mode, provides safe local emulation without requiring external credentials.
 */

import { isEmulatorMode } from "./emulator.js";

export interface AIChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface AIChatOptions {
  model?: string;
  temperature?: number;
  maxTokens?: number;
  stream?: boolean;
  appKey?: string;
  appId?: string;
  identityHeader?: string;
  gatewayUrl?: string;
}

export interface AIUsageMetrics {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
}

export interface AIChatResponse {
  id: string;
  model: string;
  content: string;
  finish_reason: string;
  usage: AIUsageMetrics;
}

export interface AIStreamChunk {
  delta: string;
  finish_reason?: string | null;
  usage?: AIUsageMetrics;
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
  recent_requests: any[];
}

export class AIGatewayError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly statusCode: number,
    public readonly details?: any,
  ) {
    super(message);
    this.name = "AIGatewayError";
  }
}

export class PlatformAIClient {
  private getBaseUrl(options?: AIChatOptions): string {
    return (
      options?.gatewayUrl ||
      process.env.CAPSULE_GATEWAY_URL ||
      process.env.CAPSULE_BROKER_URL ||
      process.env.CONTROL_PLANE_URL ||
      "http://localhost:8000"
    ).replace(/\/$/, "");
  }

  private getHeaders(options?: AIChatOptions): Record<string, string> {
    const appKey =
      options?.appKey ||
      process.env.CAPSULE_KEY ||
      process.env.CAPSULE_ID ||
      "current-app";

    const appId = options?.appId || process.env.CAPSULE_APP_ID || "";

    const identityHeader =
      options?.identityHeader || process.env.CAPSULE_IDENTITY_TOKEN || "";

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "x-capsule-key": appKey,
    };

    if (appId) {
      headers["x-capsule-id"] = appId;
    }
    if (identityHeader) {
      headers["x-capsule-identity"] = identityHeader;
    }

    return headers;
  }

  /**
   * Generates a complete AI chat completion response.
   */
  async chat(
    messages: AIChatMessage[],
    options: AIChatOptions = {},
  ): Promise<AIChatResponse> {
    // 1. Emulator Mode Fallback
    if (
      isEmulatorMode() &&
      !process.env.CONTROL_PLANE_URL &&
      !process.env.CAPSULE_GATEWAY_URL &&
      !options.gatewayUrl
    ) {
      return this.emulateChat(messages, options);
    }

    // 2. Gateway API Call
    const baseUrl = this.getBaseUrl(options);
    const endpoint = `${baseUrl}/v1/ai/chat`;

    const body: Record<string, any> = {
      messages,
      stream: false,
    };
    if (options.model) body.model = options.model;
    if (options.temperature !== undefined)
      body.temperature = options.temperature;
    if (options.maxTokens !== undefined) body.max_tokens = options.maxTokens;
    if (options.appKey) body.app_key = options.appKey;
    if (options.appId) body.app_id = options.appId;

    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: this.getHeaders(options),
        body: JSON.stringify(body),
      });
    } catch (err: any) {
      throw new AIGatewayError(
        `Failed to reach AI Gateway at ${endpoint}: ${err.message}`,
        "GATEWAY_UNREACHABLE",
        503,
      );
    }

    if (!response.ok) {
      let errPayload: any = {};
      try {
        errPayload = await response.json();
      } catch {
        errPayload = { message: await response.text() };
      }
      const detail = errPayload.detail || errPayload;
      throw new AIGatewayError(
        detail.message ||
          `AI Gateway request failed with HTTP ${response.status}`,
        detail.code || "GATEWAY_ERROR",
        response.status,
        detail,
      );
    }

    return (await response.json()) as AIChatResponse;
  }

  /**
   * Streams response chunks via Server-Sent Events (SSE).
   */
  async *stream(
    messages: AIChatMessage[],
    options: AIChatOptions = {},
  ): AsyncGenerator<AIStreamChunk, void, unknown> {
    if (
      isEmulatorMode() &&
      !process.env.CONTROL_PLANE_URL &&
      !process.env.CAPSULE_GATEWAY_URL &&
      !options.gatewayUrl
    ) {
      const emu = await this.emulateChat(messages, options);
      yield { delta: emu.content, finish_reason: "stop", usage: emu.usage };
      return;
    }

    const baseUrl = this.getBaseUrl(options);
    const endpoint = `${baseUrl}/v1/ai/chat`;

    const body: Record<string, any> = {
      messages,
      stream: true,
    };
    if (options.model) body.model = options.model;
    if (options.temperature !== undefined)
      body.temperature = options.temperature;
    if (options.maxTokens !== undefined) body.max_tokens = options.maxTokens;
    if (options.appKey) body.app_key = options.appKey;
    if (options.appId) body.app_id = options.appId;

    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: {
          ...this.getHeaders(options),
          Accept: "text/event-stream",
        },
        body: JSON.stringify(body),
      });
    } catch (err: any) {
      throw new AIGatewayError(
        `Failed to connect to AI Gateway stream at ${endpoint}: ${err.message}`,
        "GATEWAY_UNREACHABLE",
        503,
      );
    }

    if (!response.ok) {
      let errPayload: any = {};
      try {
        errPayload = await response.json();
      } catch {
        errPayload = { message: await response.text() };
      }
      const detail = errPayload.detail || errPayload;
      throw new AIGatewayError(
        detail.message ||
          `AI Gateway stream failed with HTTP ${response.status}`,
        detail.code || "GATEWAY_ERROR",
        response.status,
        detail,
      );
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new AIGatewayError(
        "Response body is not readable.",
        "STREAM_ERROR",
        500,
      );
    }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(":")) continue;

        if (trimmed.startsWith("data: ")) {
          const dataStr = trimmed.substring(6).trim();
          if (dataStr === "[DONE]") {
            return;
          }
          try {
            const parsed = JSON.parse(dataStr);
            yield parsed as AIStreamChunk;
          } catch {
            // Ignore non-JSON stream data
          }
        }
      }
    }
  }

  /**
   * Retrieves usage and monthly budget metrics for the current application.
   */
  async getUsage(options?: {
    appId?: string;
    appKey?: string;
    gatewayUrl?: string;
  }): Promise<AppAIUsage> {
    const baseUrl = this.getBaseUrl(options);
    const appId = options?.appId || process.env.CAPSULE_APP_ID;
    if (!appId) {
      throw new AIGatewayError(
        "appId is required to query app usage.",
        "APP_ID_REQUIRED",
        400,
      );
    }

    const endpoint = `${baseUrl}/v1/apps/${encodeURIComponent(appId)}/ai/usage`;
    const response = await fetch(endpoint, {
      headers: this.getHeaders(options),
    });

    if (!response.ok) {
      throw new AIGatewayError(
        `Failed to fetch AI usage: HTTP ${response.status}`,
        "GATEWAY_ERROR",
        response.status,
      );
    }

    return (await response.json()) as AppAIUsage;
  }

  private emulateChat(
    messages: AIChatMessage[],
    options: AIChatOptions,
  ): AIChatResponse {
    const userPrompt = messages
      .filter((m) => m.role === "user")
      .map((m) => m.content)
      .join(" ");
    const model = options.model || "fake-llm";
    const content = `[Local Emulator AI: ${model}] Simulated response to prompt: "${userPrompt.slice(0, 50)}..."`;
    const promptTokens = Math.max(1, Math.ceil(userPrompt.length / 4));
    const compTokens = Math.max(1, Math.ceil(content.length / 4));

    return {
      id: `emu-${Date.now()}`,
      model,
      content,
      finish_reason: "stop",
      usage: {
        prompt_tokens: promptTokens,
        completion_tokens: compTokens,
        total_tokens: promptTokens + compTokens,
        estimated_cost_usd: promptTokens * 0.000001 + compTokens * 0.000002,
      },
    };
  }
}

let defaultAIClient: PlatformAIClient | null = null;

export function getAI(): PlatformAIClient {
  if (!defaultAIClient) {
    defaultAIClient = new PlatformAIClient();
  }
  return defaultAIClient;
}
