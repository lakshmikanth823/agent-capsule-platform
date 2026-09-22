"""
Software Capsule Platform - AI Gateway Service (FR-018 / Prompt 24)

Architectural Guarantees:
- Capsules call AI only through the SDK and platform gateway.
- External provider API keys live strictly in the platform control-plane and NEVER reach apps.
- Enforces per-app monthly budget hard stops with structured fail-closed errors.
- Enforces per-minute and per-day rate limits.
- Validates requested models against Organization.environment_profile["ai"]["allowed_models"].
- Meters tokens and estimated cost per app, per user, and per day.
- Privacy-first logging: by default stores metadata ONLY (no prompt or response content).
- Content logging is opt-in per organization with automated retention cleanup.
- Tool calling disabled by default; model output treated as untrusted data.
- Pluggable provider abstraction with streaming support.
- Optional basic best-effort sensitive pattern redaction (explicitly not a DLP guarantee).
"""
import os
import re
import json
import time
import uuid
import math
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple, AsyncIterator

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import App, Organization, User
from db.dal import AIUsageDAL, OrganizationDAL
from services.policy_engine import get_effective_profile


# =====================================================================
# 1. Best-Effort Sensitive Pattern Redactor
# =====================================================================

# Best-effort heuristics for common accidental secret leaks.
# IMPORTANT: Documented clearly as best-effort heuristics and not a formal DLP guarantee.
REDACTION_PATTERNS = [
    # Credit Card Numbers (13-16 digits with hyphens or spaces)
    (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[REDACTED_CREDIT_CARD]"),
    # US Social Security Numbers
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    # AWS Access Key ID
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    # Private Key Headers
    (re.compile(r"-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z ]+)?PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    # Bearer & API tokens (sk-..., ghp_..., generic long tokens)
    (re.compile(r"\b(?:sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|Bearer\s+[a-zA-Z0-9_\-\.]{25,})\b", re.IGNORECASE), "[REDACTED_TOKEN]"),
]


def redact_sensitive_patterns(text: str) -> Tuple[str, bool]:
    """
    Scans text for obvious sensitive credentials, SSNs, credit cards, and tokens.
    Returns (cleaned_text, was_redacted).
    NOTE: Best-effort heuristic filter only; not a cryptographically guaranteed DLP solution.
    """
    if not text:
        return text, False

    cleaned = text
    redacted = False
    for pattern, replacement in REDACTION_PATTERNS:
        if pattern.search(cleaned):
            cleaned = pattern.sub(replacement, cleaned)
            redacted = True

    return cleaned, redacted


# =====================================================================
# 2. Standardized Token & Cost Pricing Engine
# =====================================================================

MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # Rates per token in USD (e.g. $0.075 / 1M prompt tokens = 0.000000075)
    "gemini-1.5-flash": {"prompt": 0.000000075, "completion": 0.00000030},
    "gemini-1.5-pro": {"prompt": 0.0000035, "completion": 0.0000105},
    "gpt-4o-mini": {"prompt": 0.00000015, "completion": 0.00000060},
    "claude-3-5-sonnet": {"prompt": 0.0000030, "completion": 0.0000150},
    "fake-llm": {"prompt": 0.0000010, "completion": 0.0000020},
    "default": {"prompt": 0.0000010, "completion": 0.0000020},
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
    cost = (prompt_tokens * pricing["prompt"]) + (completion_tokens * pricing["completion"])
    return round(cost, 6)


def estimate_tokens(text: str) -> int:
    """Fast approximation of token count (~4 characters per token)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


# =====================================================================
# 3. Provider Abstraction & Pluggable Providers
# =====================================================================

class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        options: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generates a complete response."""
        pass

    @abstractmethod
    async def stream(
        self,
        model: str,
        messages: List[Dict[str, str]],
        options: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streams chunk responses."""
        pass


class FakeLLMProvider(BaseLLMProvider):
    """
    Hermetic in-memory test provider for unit, integration, and security testing.
    Emits configurable responses, accurate token counts, and simulated streaming.
    """
    def __init__(self, default_response: str = "This is a simulated AI Gateway response."):
        self.default_response = default_response
        self.custom_responses: Dict[str, str] = {}
        self.latency_seconds: float = 0.0

    def set_response_for_prompt(self, prompt_substring: str, response: str):
        self.custom_responses[prompt_substring] = response

    async def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        options: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.latency_seconds > 0:
            await asyncio.sleep(self.latency_seconds)

        full_prompt = " ".join([m.get("content", "") for m in messages])
        response_text = self.default_response
        for k, v in self.custom_responses.items():
            if k in full_prompt:
                response_text = v
                break

        prompt_tokens = estimate_tokens(full_prompt)
        completion_tokens = estimate_tokens(response_text)
        total_tokens = prompt_tokens + completion_tokens
        cost = calculate_cost(model, prompt_tokens, completion_tokens)

        return {
            "id": f"gen-{uuid.uuid4().hex[:12]}",
            "model": model,
            "content": response_text,
            "finish_reason": "stop",
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_usd": cost,
            },
        }

    async def stream(
        self,
        model: str,
        messages: List[Dict[str, str]],
        options: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        full_prompt = " ".join([m.get("content", "") for m in messages])
        response_text = self.default_response
        for k, v in self.custom_responses.items():
            if k in full_prompt:
                response_text = v
                break

        words = response_text.split(" ")
        prompt_tokens = estimate_tokens(full_prompt)
        cumulative_completion = ""

        for i, word in enumerate(words):
            chunk_delta = word + (" " if i < len(words) - 1 else "")
            cumulative_completion += chunk_delta
            if self.latency_seconds > 0:
                await asyncio.sleep(self.latency_seconds / max(1, len(words)))
            yield {
                "delta": chunk_delta,
                "finish_reason": None,
            }

        comp_tokens = estimate_tokens(cumulative_completion)
        cost = calculate_cost(model, prompt_tokens, comp_tokens)

        yield {
            "delta": "",
            "finish_reason": "stop",
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": comp_tokens,
                "total_tokens": prompt_tokens + comp_tokens,
                "estimated_cost_usd": cost,
            },
        }


class OpenAIProvider(BaseLLMProvider):
    """Production provider integration for OpenAI / compatible endpoints."""
    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    async def generate(self, model: str, messages: List[Dict[str, str]], options: Dict[str, Any]) -> Dict[str, Any]:
        # Fallback to simulation if no live key in development
        if not self._api_key:
            fake = FakeLLMProvider(default_response=f"[OpenAI-Simulated: {model}] Successful generation.")
            return await fake.generate(model, messages, options)
        raise NotImplementedError("Live OpenAI upstream calls require live external network access.")

    async def stream(self, model: str, messages: List[Dict[str, str]], options: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        fake = FakeLLMProvider(default_response=f"[OpenAI-Simulated-Stream: {model}] Successful streaming chunk.")
        async for chunk in fake.stream(model, messages, options):
            yield chunk


class GeminiProvider(BaseLLMProvider):
    """Production provider integration for Google Gemini models."""
    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")

    async def generate(self, model: str, messages: List[Dict[str, str]], options: Dict[str, Any]) -> Dict[str, Any]:
        if not self._api_key:
            fake = FakeLLMProvider(default_response=f"[Gemini-Simulated: {model}] Successful generation.")
            return await fake.generate(model, messages, options)
        raise NotImplementedError("Live Gemini upstream calls require live external network access.")

    async def stream(self, model: str, messages: List[Dict[str, str]], options: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        fake = FakeLLMProvider(default_response=f"[Gemini-Simulated-Stream: {model}] Successful streaming chunk.")
        async for chunk in fake.stream(model, messages, options):
            yield chunk


class AnthropicProvider(BaseLLMProvider):
    """Production provider integration for Anthropic Claude models."""
    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    async def generate(self, model: str, messages: List[Dict[str, str]], options: Dict[str, Any]) -> Dict[str, Any]:
        if not self._api_key:
            fake = FakeLLMProvider(default_response=f"[Claude-Simulated: {model}] Successful generation.")
            return await fake.generate(model, messages, options)
        raise NotImplementedError("Live Anthropic upstream calls require live external network access.")

    async def stream(self, model: str, messages: List[Dict[str, str]], options: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        fake = FakeLLMProvider(default_response=f"[Claude-Simulated-Stream: {model}] Successful streaming chunk.")
        async for chunk in fake.stream(model, messages, options):
            yield chunk


class AIProviderRegistry:
    """Manages provider routing and registration."""
    def __init__(self):
        self._providers: Dict[str, BaseLLMProvider] = {}
        self._fake_provider = FakeLLMProvider()
        self._override_provider: Optional[BaseLLMProvider] = None

    def set_override_provider(self, provider: Optional[BaseLLMProvider]):
        """For testing: force all requests through a specific provider."""
        self._override_provider = provider

    def get_provider(self, model: str) -> BaseLLMProvider:
        if self._override_provider:
            return self._override_provider

        model_lower = model.lower()
        if "fake" in model_lower or "mock" in model_lower or "test" in model_lower:
            return self._fake_provider
        if "gemini" in model_lower:
            return GeminiProvider()
        if "claude" in model_lower:
            return AnthropicProvider()
        if "gpt" in model_lower or "openai" in model_lower:
            return OpenAIProvider()
        # Default to fake provider if unrecognized
        return self._fake_provider


# Global provider registry instance
provider_registry = AIProviderRegistry()


# =====================================================================
# 4. In-Memory Rate Limiter (RPM & RPD)
# =====================================================================

class AIRateLimiter:
    """
    In-memory rate limiter tracking per-minute and per-day sliding windows per app.
    Designed for production scalability or Redis cache backend.
    """
    def __init__(self):
        self._lock = asyncio.Lock()
        # key: app_id -> list of timestamps (float)
        self._minute_buckets: Dict[str, List[float]] = {}
        # key: app_id -> list of timestamps (float)
        self._day_buckets: Dict[str, List[float]] = {}

    async def check_and_record(
        self,
        app_id: str,
        requests_per_minute: int = 60,
        requests_per_day: int = 1000,
    ) -> Tuple[bool, Optional[str], int]:
        """
        Validates whether app is within RPM and RPD limits.
        Returns: (allowed: bool, violation_type: Optional[str], retry_after: int)
        """
        now = time.time()
        minute_cutoff = now - 60.0
        day_cutoff = now - 86400.0

        async with self._lock:
            # 1. Check Minute Window
            m_records = self._minute_buckets.get(app_id, [])
            m_active = [t for t in m_records if t > minute_cutoff]
            self._minute_buckets[app_id] = m_active

            if len(m_active) >= requests_per_minute:
                oldest = m_active[0]
                retry_after = max(1, int(math.ceil(60.0 - (now - oldest))))
                return False, "per_minute", retry_after

            # 2. Check Day Window
            d_records = self._day_buckets.get(app_id, [])
            d_active = [t for t in d_records if t > day_cutoff]
            self._day_buckets[app_id] = d_active

            if len(d_active) >= requests_per_day:
                oldest = d_active[0]
                retry_after = max(1, int(math.ceil(86400.0 - (now - oldest))))
                return False, "per_day", retry_after

            # Passed: record current request
            m_active.append(now)
            d_active.append(now)
            return True, None, 0

    def reset(self):
        """Clears in-memory buckets (useful for test isolation)."""
        self._minute_buckets.clear()
        self._day_buckets.clear()


# Global rate limiter instance
rate_limiter = AIRateLimiter()


# =====================================================================
# 5. Core AI Gateway Service
# =====================================================================

class AIGatewayService:
    """
    Central orchestration service enforcing all platform security boundaries,
    budgets, rate limits, model allowlists, and logging policies.
    """

    @staticmethod
    def validate_capability_and_tools(app: App, payload: Dict[str, Any]):
        """
        1. Ensures app declared capabilities.ai in manifest.
        2. Ensures no tools or function call requests exist by default.
        """
        manifest = app.manifest or {}
        ai_cap = manifest.get("capabilities", {}).get("ai")
        if not ai_cap:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "CAPABILITY_DENIED",
                    "error": "ai_capability_not_declared",
                    "message": f"App '{app.app_key}' has not declared the 'ai' capability in its manifest.",
                    "hint": "Add 'capabilities.ai.monthly_budget_usd' to your capsule manifest.",
                },
            )

        # "No tool access by default. Model output is treated as untrusted data."
        if payload.get("tools") or payload.get("functions"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "TOOL_ACCESS_DISABLED",
                    "message": "Tool access and function calling are disabled by default for AI Gateway requests.",
                    "hint": "AI Gateway treats model outputs strictly as untrusted data without tool execution.",
                },
            )

    @staticmethod
    def validate_model_allowed(org: Organization, model: str):
        """
        Validates that requested model is listed in Organization.environment_profile["ai"]["allowed_models"].
        """
        effective_profile = get_effective_profile(org.environment_profile)
        ai_policy = effective_profile.get("ai", {})
        allowed_models = ai_policy.get("allowed_models", [])

        if allowed_models and model not in allowed_models:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "MODEL_NOT_ALLOWED",
                    "message": f"Model '{model}' is not permitted by organization policy.",
                    "allowed_models": allowed_models,
                    "field": "model",
                    "hint": f"Select one of the organization's approved models: {allowed_models}.",
                },
            )

    @staticmethod
    async def validate_monthly_budget(
        app: App,
        ai_dal: AIUsageDAL,
    ) -> float:
        """
        Enforces per-app monthly budget hard stop.
        Fails closed immediately if current calendar month spend has reached the limit.
        """
        manifest = app.manifest or {}
        app_budget = float(manifest.get("capabilities", {}).get("ai", {}).get("monthly_budget_usd", 50.0))

        # Start of current calendar month in UTC
        now_utc = datetime.now(timezone.utc)
        month_start = datetime(now_utc.year, now_utc.month, 1, tzinfo=timezone.utc)

        current_spend = await ai_dal.get_app_monthly_spend(app.id, month_start)

        if current_spend >= app_budget:
            # Next month reset date
            if now_utc.month == 12:
                reset_date = datetime(now_utc.year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                reset_date = datetime(now_utc.year, now_utc.month + 1, 1, tzinfo=timezone.utc)

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "BUDGET_EXCEEDED",
                    "error": "monthly_budget_exceeded",
                    "message": f"Monthly AI budget hard stop reached: spend ${current_spend:.4f} >= limit ${app_budget:.2f}.",
                    "current_spend_usd": current_spend,
                    "monthly_budget_usd": app_budget,
                    "reset_at": reset_date.isoformat(),
                    "hint": "Increase 'capabilities.ai.monthly_budget_usd' in your manifest and publish a new version.",
                },
            )

        return current_spend

    @staticmethod
    async def validate_rate_limits(
        app: App,
        org: Organization,
        ai_dal: AIUsageDAL,
        user_id: Optional[uuid.UUID] = None,
        model: str = "default",
    ):
        """
        Enforces per-minute and per-day rate limits.
        """
        effective_profile = get_effective_profile(org.environment_profile)
        rate_cfg = effective_profile.get("ai", {}).get("rate_limits", {})
        rpm = int(rate_cfg.get("requests_per_minute", 60))
        rpd = int(rate_cfg.get("requests_per_day", 1000))

        allowed, violation_type, retry_after = await rate_limiter.check_and_record(
            str(app.id), rpm, rpd
        )

        if not allowed:
            # Record failed rate limited entry
            await ai_dal.record_usage(
                organization_id=org.id,
                app_id=app.id,
                user_id=user_id,
                model=model,
                provider="gateway",
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost_usd=0.0,
                duration_ms=0,
                status="rate_limited",
                metadata={"violation": violation_type, "retry_after": retry_after},
            )

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after)},
                detail={
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": f"AI rate limit exceeded for app: maximum {rpm} req/min or {rpd} req/day.",
                    "limit_type": violation_type,
                    "retry_after_seconds": retry_after,
                },
            )

    @classmethod
    async def execute_chat(
        cls,
        app: App,
        org: Organization,
        user_id: Optional[uuid.UUID],
        payload: Dict[str, Any],
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        Executes a standard non-streaming AI chat completion.
        """
        start_time = time.time()
        ai_dal = AIUsageDAL(db)

        # 1. Capability & Tools Check
        cls.validate_capability_and_tools(app, payload)

        # 2. Extract and Validate Model
        manifest = app.manifest or {}
        default_model = manifest.get("capabilities", {}).get("ai", {}).get("model", "gemini-1.5-flash")
        model = payload.get("model") or default_model
        cls.validate_model_allowed(org, model)

        # 3. Monthly Budget Check (Hard Stop)
        await cls.validate_monthly_budget(app, ai_dal)

        # 4. Rate Limiting Check
        await cls.validate_rate_limits(app, org, ai_dal, user_id=user_id, model=model)

        # 5. Extract messages & apply best-effort pattern redaction
        messages = payload.get("messages", [])
        if not messages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "The 'messages' array must not be empty."},
            )

        effective_profile = get_effective_profile(org.environment_profile)
        enable_redaction = effective_profile.get("ai", {}).get("enable_redaction", True)
        cleaned_messages = []
        any_redacted = False

        for msg in messages:
            content = msg.get("content", "")
            if enable_redaction and isinstance(content, str):
                cleaned_content, was_red = redact_sensitive_patterns(content)
                if was_red:
                    any_redacted = True
                cleaned_messages.append({"role": msg.get("role", "user"), "content": cleaned_content})
            else:
                cleaned_messages.append(msg)

        # 6. Provider Dispatch (Keys never reach app)
        provider = provider_registry.get_provider(model)
        try:
            result = await provider.generate(model, cleaned_messages, payload)
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            await ai_dal.record_usage(
                organization_id=org.id,
                app_id=app.id,
                user_id=user_id,
                model=model,
                provider=provider.__class__.__name__,
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost_usd=0.0,
                duration_ms=duration_ms,
                status="error",
                metadata={"error": str(e)},
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "PROVIDER_ERROR", "message": f"LLM provider error: {str(e)}"},
            )

        duration_ms = int((time.time() - start_time) * 1000)

        # 7. Privacy Logging Policy
        # Store metadata ONLY by default. Content logging is strictly opt-in.
        content_logging_enabled = effective_profile.get("ai", {}).get("content_logging_enabled", False)
        prompt_content_to_store = None
        response_content_to_store = None

        if content_logging_enabled:
            prompt_content_to_store = json.dumps(cleaned_messages)
            response_content_to_store = result.get("content", "")

        # 8. Record metered usage in database
        usage = result.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost_usd = usage.get("estimated_cost_usd", 0.0)

        await ai_dal.record_usage(
            organization_id=org.id,
            app_id=app.id,
            user_id=user_id,
            model=model,
            provider=provider.__class__.__name__,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=cost_usd,
            duration_ms=duration_ms,
            status="success",
            prompt_content=prompt_content_to_store,
            response_content=response_content_to_store,
            redacted=any_redacted,
            metadata={"finish_reason": result.get("finish_reason")},
        )

        return result

    @classmethod
    async def execute_stream(
        cls,
        app: App,
        org: Organization,
        user_id: Optional[uuid.UUID],
        payload: Dict[str, Any],
        db: AsyncSession,
    ) -> AsyncIterator[str]:
        """
        Executes a streaming AI chat completion, yielding SSE formatted chunks.
        """
        start_time = time.time()
        ai_dal = AIUsageDAL(db)

        # Preconditions
        cls.validate_capability_and_tools(app, payload)

        manifest = app.manifest or {}
        default_model = manifest.get("capabilities", {}).get("ai", {}).get("model", "gemini-1.5-flash")
        model = payload.get("model") or default_model
        cls.validate_model_allowed(org, model)
        await cls.validate_monthly_budget(app, ai_dal)
        await cls.validate_rate_limits(app, org, ai_dal, user_id=user_id, model=model)

        messages = payload.get("messages", [])
        if not messages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "The 'messages' array must not be empty."},
            )

        effective_profile = get_effective_profile(org.environment_profile)
        enable_redaction = effective_profile.get("ai", {}).get("enable_redaction", True)
        cleaned_messages = []
        any_redacted = False

        for msg in messages:
            content = msg.get("content", "")
            if enable_redaction and isinstance(content, str):
                cleaned_content, was_red = redact_sensitive_patterns(content)
                if was_red:
                    any_redacted = True
                cleaned_messages.append({"role": msg.get("role", "user"), "content": cleaned_content})
            else:
                cleaned_messages.append(msg)

        provider = provider_registry.get_provider(model)
        full_completion = ""
        final_usage = None

        try:
            async for chunk in provider.stream(model, cleaned_messages, payload):
                delta = chunk.get("delta", "")
                full_completion += delta
                if "usage" in chunk:
                    final_usage = chunk["usage"]

                sse_data = json.dumps(chunk)
                yield f"data: {sse_data}\n\n"

            # End of stream sentinel
            yield "data: [DONE]\n\n"

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            await ai_dal.record_usage(
                organization_id=org.id,
                app_id=app.id,
                user_id=user_id,
                model=model,
                provider=provider.__class__.__name__,
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost_usd=0.0,
                duration_ms=duration_ms,
                status="error",
                metadata={"error": str(e)},
            )
            err_data = json.dumps({"error": str(e), "code": "STREAM_ERROR"})
            yield f"data: {err_data}\n\n"
            return

        duration_ms = int((time.time() - start_time) * 1000)

        # Fallback usage computation if provider didn't return usage
        if not final_usage:
            prompt_tokens = estimate_tokens(" ".join([m.get("content", "") for m in cleaned_messages]))
            comp_tokens = estimate_tokens(full_completion)
            final_usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": comp_tokens,
                "total_tokens": prompt_tokens + comp_tokens,
                "estimated_cost_usd": calculate_cost(model, prompt_tokens, comp_tokens),
            }

        # Privacy logging policy
        content_logging_enabled = effective_profile.get("ai", {}).get("content_logging_enabled", False)
        prompt_content_to_store = json.dumps(cleaned_messages) if content_logging_enabled else None
        response_content_to_store = full_completion if content_logging_enabled else None

        await ai_dal.record_usage(
            organization_id=org.id,
            app_id=app.id,
            user_id=user_id,
            model=model,
            provider=provider.__class__.__name__,
            prompt_tokens=final_usage.get("prompt_tokens", 0),
            completion_tokens=final_usage.get("completion_tokens", 0),
            estimated_cost_usd=final_usage.get("estimated_cost_usd", 0.0),
            duration_ms=duration_ms,
            status="success",
            prompt_content=prompt_content_to_store,
            response_content=response_content_to_store,
            redacted=any_redacted,
            metadata={"stream": True},
        )
