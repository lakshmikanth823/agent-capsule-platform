import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { sdk, getAI, PlatformAIClient, AIGatewayError } from '../src/index.js';

describe('Capsule SDK AI Gateway Client', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    process.env = originalEnv;
    vi.restoreAllMocks();
  });

  it('should expose sdk.ai as an instance of PlatformAIClient', () => {
    expect(sdk.ai).toBeDefined();
    expect(sdk.ai).toBeInstanceOf(PlatformAIClient);
    expect(getAI()).toBe(sdk.ai);
  });

  it('should support safe local emulator mode when CAPSULE_EMULATOR=true', async () => {
    process.env.CAPSULE_EMULATOR = 'true';
    delete process.env.CONTROL_PLANE_URL;
    delete process.env.CAPSULE_GATEWAY_URL;

    const response = await sdk.ai.chat(
      [{ role: 'user', content: 'Hello, what is a software capsule?' }],
      { model: 'fake-llm' }
    );

    expect(response).toBeDefined();
    expect(response.id).toMatch(/^emu-/);
    expect(response.model).toBe('fake-llm');
    expect(response.content).toContain('Simulated response to prompt');
    expect(response.usage.prompt_tokens).toBeGreaterThan(0);
    expect(response.usage.total_tokens).toBeGreaterThan(0);
    expect(response.usage.estimated_cost_usd).toBeGreaterThan(0);
  });

  it('should support streaming generator in local emulator mode', async () => {
    process.env.CAPSULE_EMULATOR = 'true';
    delete process.env.CONTROL_PLANE_URL;
    delete process.env.CAPSULE_GATEWAY_URL;

    const chunks = [];
    for await (const chunk of sdk.ai.stream(
      [{ role: 'user', content: 'Stream this message.' }],
      { model: 'fake-llm' }
    )) {
      chunks.push(chunk);
    }

    expect(chunks.length).toBeGreaterThan(0);
    expect(chunks[0].delta).toBeDefined();
    expect(chunks[0].finish_reason).toBe('stop');
  });

  it('should send proper headers and body to platform gateway endpoint', async () => {
    delete process.env.CAPSULE_EMULATOR;
    process.env.CAPSULE_KEY = 'test-leave-tracker';
    process.env.CAPSULE_APP_ID = 'app-12345';
    process.env.CAPSULE_IDENTITY_TOKEN = 'mock-identity-jwt';

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: 'gen-abc123',
        model: 'gemini-1.5-flash',
        content: 'Capsules are isolated web apps.',
        finish_reason: 'stop',
        usage: {
          prompt_tokens: 10,
          completion_tokens: 6,
          total_tokens: 16,
          estimated_cost_usd: 0.000003,
        },
      }),
    });
    global.fetch = mockFetch;

    const result = await sdk.ai.chat(
      [{ role: 'user', content: 'Explain capsules' }],
      { model: 'gemini-1.5-flash', gatewayUrl: 'http://localhost:8000' }
    );

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [callUrl, callInit] = mockFetch.mock.calls[0];
    expect(callUrl).toBe('http://localhost:8000/v1/ai/chat');
    expect(callInit.method).toBe('POST');
    expect(callInit.headers['x-capsule-key']).toBe('test-leave-tracker');
    expect(callInit.headers['x-capsule-id']).toBe('app-12345');
    expect(callInit.headers['x-capsule-identity']).toBe('mock-identity-jwt');

    const parsedBody = JSON.parse(callInit.body);
    expect(parsedBody.model).toBe('gemini-1.5-flash');
    expect(parsedBody.stream).toBe(false);
    expect(parsedBody.messages[0].content).toBe('Explain capsules');

    expect(result.id).toBe('gen-abc123');
    expect(result.content).toBe('Capsules are isolated web apps.');
  });

  it('should throw structured AIGatewayError on HTTP failure', async () => {
    delete process.env.CAPSULE_EMULATOR;

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      json: async () => ({
        detail: {
          code: 'BUDGET_EXCEEDED',
          message: 'Monthly AI budget limit of $25.00 exceeded.',
          current_spend_usd: 25.10,
        },
      }),
    });

    await expect(
      sdk.ai.chat([{ role: 'user', content: 'Generate text' }], { gatewayUrl: 'http://localhost:8000' })
    ).rejects.toThrow(AIGatewayError);

    try {
      await sdk.ai.chat([{ role: 'user', content: 'Generate text' }], { gatewayUrl: 'http://localhost:8000' });
    } catch (err: any) {
      expect(err).toBeInstanceOf(AIGatewayError);
      expect(err.code).toBe('BUDGET_EXCEEDED');
      expect(err.statusCode).toBe(429);
      expect(err.message).toContain('budget limit');
      expect(err.details.current_spend_usd).toBe(25.10);
    }
  });
});
