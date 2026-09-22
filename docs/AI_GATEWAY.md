# AI Gateway Service Architecture & Specification (Prompt 24 / FR-018)

**Date**: 2026-09-22  
**Requirement**: PRD FR-018 (AI Capability)  
**Status**: Production-Ready

---

## 1. Executive Summary & Architecture

The **AI Gateway** sits between sandboxed capsule applications and upstream Large Language Model (LLM) providers (OpenAI, Google Gemini, Anthropic, and test providers).

Capsules never communicate with LLM providers directly, nor do they hold or manage external provider API keys. All AI interactions flow exclusively through `@capsule/sdk` and the platform AI Gateway (`POST /v1/ai/chat`).

```
┌────────────────────────────────────────────────────────────────────────┐
│ Capsule Sandbox (Node.js 22 / Python)                                  │
│                                                                        │
│   sdk.ai.chat(...) / sdk.ai.stream(...)                                │
│       │                                                                │
│       │ (x-capsule-key, x-capsule-id, x-capsule-identity)             │
│       ▼                                                                │
└───────┬────────────────────────────────────────────────────────────────┘
        │
        │ HTTP / Internal IPC
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Platform AI Gateway (/v1/ai/chat)                                      │
│                                                                        │
│   1. Capability & Tool Access Check                                    │
│      - Verifies 'capabilities.ai' declared in manifest                 │
│      - Rejects any tool definitions (TOOL_ACCESS_DISABLED)             │
│                                                                        │
│   2. Model Governance                                                  │
│      - Checks model against Organization.environment_profile           │
│                                                                        │
│   3. Monthly Budget Hard Stop                                          │
│      - Sums month spend vs capabilities.ai.monthly_budget_usd          │
│      - Fails closed immediately if exceeded (BUDGET_EXCEEDED)          │
│                                                                        │
│   4. Rate Limit Sliding Window                                         │
│      - RPM & RPD checks per app (HTTP 429 + Retry-After)               │
│                                                                        │
│   5. Best-Effort Sensitive Pattern Redaction                           │
│      - Scrubs credit cards, SSNs, and secret tokens                    │
│                                                                        │
│   6. Provider Dispatch & Secure Key Injection                          │
│      - Keys fetched from Platform Secrets / Env; NEVER given to app    │
│      - Pluggable provider abstraction (OpenAI, Gemini, Anthropic, Fake)│
│                                                                        │
│   7. Privacy Logging & Metering Engine                                 │
│      - DEFAULT: Metadata ONLY (tokens, latency, cost). Content is NULL │
│      - OPT-IN: Prompt & response logged only if org enables it         │
│      - Scheduled purge enforces content retention window               │
└───────┬────────────────────────────────────────────────────────────────┘
        │
        │ Upstream TLS (Bearer Provider Keys)
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│ External LLM Providers (OpenAI, Google Gemini, Anthropic)              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Security & Architectural Guarantees

### 2.1 Zero Raw Provider Secret Exposure

- Upstream provider credentials (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) are held exclusively in the platform control-plane environment or secret vault.
- Provider keys are **never** returned in API responses, injected into sandbox environments, or exposed to capsule SDK code.
- Tested: `test_provider_keys_never_reach_the_app` in `services/control-plane/tests/test_ai_gateway.py`.

### 2.2 Hard-Stop Monthly Budget Enforcement

- Every capsule declaring AI capability specifies a monthly ceiling in its manifest:
  ```json
  "capabilities": {
    "ai": {
      "monthly_budget_usd": 10.0,
      "model": "gemini-1.5-flash"
    }
  }
  ```
- Before executing any prompt, the gateway queries `ai_usage_records` to calculate the total spend for the active calendar month (UTC).
- If `current_spend >= monthly_budget_usd`, the gateway **fails closed** immediately with HTTP 429 and a structured error envelope:
  ```json
  {
    "detail": {
      "code": "BUDGET_EXCEEDED",
      "error": "monthly_budget_exceeded",
      "message": "Monthly AI budget hard stop reached: spend $10.0000 >= limit $10.00.",
      "current_spend_usd": 10.0,
      "monthly_budget_usd": 10.0,
      "reset_at": "2026-10-01T00:00:00+00:00",
      "hint": "Increase 'capabilities.ai.monthly_budget_usd' in your manifest and publish a new version."
    }
  }
  ```

### 2.3 Rate Limiting (Sliding Window)

- Configured at the organization level via the Environment Profile (`requests_per_minute` and `requests_per_day`).
- Default: 60 requests/minute, 1,000 requests/day per app.
- Excess requests are rejected with HTTP 429, a `Retry-After: <seconds>` header, and recorded in usage logs as `rate_limited`.

### 2.4 Model Allowlist & Governance

- Models requested in payloads (`"model": "..."`) are checked against the organization's approved models list: `Organization.environment_profile["ai"]["allowed_models"]`.
- Default approved models:
  - `gemini-1.5-flash`
  - `gemini-1.5-pro`
  - `claude-3-5-sonnet`
  - `gpt-4o-mini`
  - `fake-llm` (test/emulator mode)
- Requests for unapproved models fail closed with HTTP 403 `MODEL_NOT_ALLOWED`.

### 2.5 Privacy-First Logging Policy

- **Metadata Only by Default**: By default, the platform records metadata ONLY (`prompt_tokens`, `completion_tokens`, `estimated_cost_usd`, `duration_ms`, `model`, `status`). The database columns `prompt_content` and `response_content` are strictly `NULL`.
- **Opt-In Content Logging**: An organization owner may opt into storing prompt and response content by enabling `content_logging_enabled: true` in their Environment Profile.
- **Retention & Purge**: When content logging is enabled, a retention duration (`content_retention_days`, default 30 days) is enforced. A scheduled worker or admin API endpoint (`POST /v1/organizations/{org_id}/ai/purge-content`) purges expired text content while preserving all usage metrics, tokens, and cost accounting.

### 2.6 No Tool Access by Default & Untrusted Model Outputs

- AI Gateway requests containing `tools` or `tool_choice` parameters are rejected with HTTP 403 `TOOL_ACCESS_DISABLED`.
- LLM outputs are treated strictly as untrusted text. Sandboxes must not execute arbitrary code or SQL generated by LLMs without validation.

### 2.7 Best-Effort Sensitive Pattern Redaction

- Prompts are automatically scanned for obvious accidental secret leaks before transmission to upstream providers:
  - Credit card numbers (13–16 digits with Luhn-like formatting)
  - US Social Security Numbers (`\b\d{3}-\d{2}-\d{4}\b`)
  - Obvious secret tokens (e.g. `sk-...`, `ghp_...`, `Bearer ...`)
- Matched substrings are replaced with `[REDACTED_CREDIT_CARD]`, `[REDACTED_SSN]`, or `[REDACTED_SECRET_TOKEN]`.
- Redacted requests are flagged in usage records (`redacted = true`).

> [!CAUTION]
> **Best-Effort Disclaimer**: Pattern redaction is a heuristic safety net for accidental leakage. It does **not** constitute a formal Data Loss Prevention (DLP) or compliance boundary. Developers and users must not submit unredacted sensitive PII or secrets to LLM endpoints.

---

## 3. Pluggable Provider Abstraction & Streaming

The AI Gateway defines an abstract interface `BaseLLMProvider` with synchronous/batch (`generate`) and streaming (`stream`) support:

```python
class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate(self, model: str, messages: List[Dict[str, str]], options: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def stream(self, model: str, messages: List[Dict[str, str]], options: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        pass
```

### Implementations:

1. **`FakeLLMProvider`**: High-performance hermetic provider for unit testing, CI/CD, and local emulator mode.
2. **`OpenAIProvider`**: Connects to `https://api.openai.com/v1/chat/completions` supporting `gpt-4o`, `gpt-4o-mini`, and related models.
3. **`GeminiProvider`**: Connects to Google Generative Language API (`gemini-1.5-flash`, `gemini-1.5-pro`).
4. **`AnthropicProvider`**: Connects to Anthropic Messages API (`claude-3-5-sonnet`, `claude-3-haiku`).

### Streaming Support (SSE):

When a client specifies `"stream": true`, the AI Gateway streams chunks using standard Server-Sent Events (`text/event-stream`):

```
data: {"delta": "Hello", "finish_reason": null}

data: {"delta": " world!", "finish_reason": "stop", "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7, "estimated_cost_usd": 0.00001}}

data: [DONE]
```

Upon stream completion, full token usage and estimated cost are persisted to `ai_usage_records`.

---

## 4. Database Schema: `ai_usage_records`

Created via Alembic Migration `007_ai_gateway`:

| Column               | Type           | Nullable | Description                                 |
| :------------------- | :------------- | :------: | :------------------------------------------ |
| `id`                 | `UUID`         |    No    | Primary Key                                 |
| `organization_id`    | `UUID`         |    No    | Foreign Key -> `organizations.id` (CASCADE) |
| `app_id`             | `UUID`         |    No    | Foreign Key -> `apps.id` (CASCADE)          |
| `user_id`            | `UUID`         |   Yes    | Acting user who triggered the request       |
| `model`              | `VARCHAR(128)` |    No    | Model name (e.g. `gemini-1.5-flash`)        |
| `provider`           | `VARCHAR(64)`  |    No    | Provider class/name                         |
| `prompt_tokens`      | `INTEGER`      |    No    | Number of input prompt tokens               |
| `completion_tokens`  | `INTEGER`      |    No    | Number of output completion tokens          |
| `total_tokens`       | `INTEGER`      |    No    | Sum of prompt + completion tokens           |
| `estimated_cost_usd` | `FLOAT`        |    No    | Metered cost in USD                         |
| `duration_ms`        | `INTEGER`      |    No    | Request execution time in milliseconds      |
| `status`             | `VARCHAR(32)`  |    No    | `success`, `error`, `rate_limited`          |
| `prompt_content`     | `TEXT`         |   Yes    | Serialized prompt JSON (NULL unless opt-in) |
| `response_content`   | `TEXT`         |   Yes    | LLM completion text (NULL unless opt-in)    |
| `redacted`           | `BOOLEAN`      |    No    | Whether sensitive patterns were scrubbed    |
| `metadata`           | `JSONB`        |   Yes    | Finish reason, error details, stream flag   |
| `created_at`         | `TIMESTAMPTZ`  |    No    | Record creation timestamp (UTC)             |

---

## 5. API Reference

### `POST /v1/ai/chat`

Executes an AI completion or streaming session.

- **Headers**:
  - `x-capsule-key`: App publish token or API key
  - `x-capsule-id`: Application UUID
  - `x-capsule-identity`: Signed identity token of the acting user (optional)
- **Body**:
  ```json
  {
    "model": "gemini-1.5-flash",
    "messages": [
      { "role": "system", "content": "You are a customer assistant." },
      { "role": "user", "content": "How do I request time off?" }
    ],
    "stream": false,
    "temperature": 0.7,
    "max_tokens": 1000
  }
  ```
- **Response (200 OK)**:
  ```json
  {
    "id": "ai-chat-61a0f67175494297a73646545b7ee974",
    "model": "gemini-1.5-flash",
    "content": "To request time off, visit the Leave Tracker app...",
    "finish_reason": "stop",
    "usage": {
      "prompt_tokens": 24,
      "completion_tokens": 42,
      "total_tokens": 66,
      "estimated_cost_usd": 0.000085
    }
  }
  ```

### `GET /v1/apps/{app_id}/ai/usage`

Returns monthly budget utilization, spend, and lifetime token counts for a capsule.

### `GET /v1/organizations/{org_id}/ai/usage`

Returns aggregated AI usage metrics, top models by spend, and app-by-app budget utilization.

### `GET /v1/organizations/{org_id}/ai/requests`

Returns paginated list of AI invocations with filters for app, user, model, status, and time range.

### `POST /v1/organizations/{org_id}/ai/purge-content`

Admin action to purge prompt and response text older than `retention_days`, while keeping token and cost metrics permanently.

---

## 6. SDK Integration (`@capsule/sdk`)

Sandboxed applications interact with the AI Gateway using `@capsule/sdk`:

```typescript
import { sdk } from "@capsule/sdk";

// 1. Standard Chat Completion
const response = await sdk.ai.chat({
  messages: [{ role: "user", content: "Summarize the employee handbook." }],
  temperature: 0.2,
});
console.log(response.content);
console.log(
  `Tokens: ${response.usage.total_tokens}, Cost: $${response.usage.estimated_cost_usd}`,
);

// 2. Streaming Response
for await (const chunk of sdk.ai.stream({
  messages: [{ role: "user", content: "Generate a long report." }],
})) {
  process.stdout.write(chunk.delta);
}

// 3. Inspect Current App AI Budget Utilization
const usage = await sdk.ai.getUsage();
console.log(
  `Monthly spend: $${usage.current_spend_usd} / $${usage.monthly_budget_usd}`,
);
```

---

## 7. Dashboard UI: AI Gateway Screen

The Capsule Platform Dashboard provides a dedicated **AI Gateway** management screen (`apps/dashboard/src/screens/AIGatewayScreen.tsx`):

- **KPI Summary Cards**: Month-to-Date Spend, Total Tokens Metered, Active Capsules, and Total Invocations.
- **App Budget Utilization Table**: Visual progress bars showing spend vs monthly budget limit, budget warnings (> 80%), and hard stop alerts (> 100%).
- **Model Usage Breakdown**: Interactive visual cost distribution across permitted models.
- **Invocations Log Viewer**: Searchable, filterable audit log of every AI request with status badges (`success`, `rate_limited`, `error`, `redacted`).
- **Content Purge Tool**: Organization admin modal for manually triggering content retention purges.
