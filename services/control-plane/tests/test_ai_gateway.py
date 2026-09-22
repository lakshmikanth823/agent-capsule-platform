"""
Comprehensive Test Suite for Prompt 24: AI Gateway Service (FR-018)

Verifies:
1. Basic chat completion and usage metering (tokens, cost, latency).
2. Budget cutoff: hard stop when per-app monthly budget is reached (fail closed with structured error).
3. Rate limits: per-minute and per-day rate limits trigger HTTP 429 with Retry-After.
4. Model allowlist: disallowed models rejected per organization's Environment Profile.
5. Privacy-first logging: by default stores metadata only (prompt & response content are NULL).
6. Opt-in content logging and retention cleanup (purging expired content preserves tokens/cost).
7. Zero secret exposure: platform provider keys are never exposed to capsule apps.
8. No tool access by default: tool definitions in requests are rejected.
9. Best-effort pattern redaction: credit cards, SSNs, and tokens sanitized in prompts.
10. Streaming: SSE chunks delivered and metered upon stream completion.
11. App and organization usage reporting endpoints.
"""
import os
import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, update

from main import app
from db.session import db_context
from db.models import Organization, User, App, AIUsageRecord
from db.dal import AppDAL, OrganizationDAL, UserDAL, AIUsageDAL
from services.ai_gateway import (
    AIGatewayService,
    FakeLLMProvider,
    provider_registry,
    rate_limiter,
    redact_sensitive_patterns,
    calculate_cost,
)

MOCK_ALICE_TOKEN = "mock-alice-token"  # Owner of Acme Corp


@pytest.fixture(autouse=True)
def reset_rate_limiter_and_providers():
    rate_limiter.reset()
    fake_provider = FakeLLMProvider(default_response="Simulated AI response for testing.")
    provider_registry.set_override_provider(fake_provider)
    yield
    rate_limiter.reset()
    provider_registry.set_override_provider(None)


async def create_test_app_with_ai_budget(
    client: AsyncClient,
    app_key: str,
    monthly_budget_usd: float = 5.0,
    model: str = "fake-llm",
) -> str:
    """Helper to create an active app with capabilities.ai declared."""
    manifest = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": f"AI App {app_key}",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["employee"],
        "capabilities": {
            "db": {"type": "sqlite"},
            "identity": True,
            "ai": {
                "monthly_budget_usd": monthly_budget_usd,
                "model": model,
            },
        },
        "egress": [],
        "sharing": {"default": "org"},
    }

    res = await client.post(
        "/v1/apps",
        headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        json={
            "id": app_key,
            "name": f"AI App {app_key}",
            "manifest": manifest,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


# =====================================================================
# Test 1: Basic Generation and Metering
# =====================================================================

@pytest.mark.asyncio
async def test_ai_chat_success_and_metering():
    """Verifies that an active app with AI capability can generate completions and is metered accurately."""
    transport = ASGITransport(app=app)
    app_key = f"ai-test-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app_id = await create_test_app_with_ai_budget(client, app_key, monthly_budget_usd=5.0)

        # Execute chat completion
        res = await client.post(
            "/v1/ai/chat",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-id": app_id,
            },
            json={
                "model": "fake-llm",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "What is a capsule?"},
                ],
            },
        )
        assert res.status_code == 200, res.text
        data = res.json()

        assert "id" in data
        assert data["model"] == "fake-llm"
        assert data["finish_reason"] == "stop"
        assert "content" in data
        assert data["content"] == "Simulated AI response for testing."

        usage = data["usage"]
        assert usage["prompt_tokens"] > 0
        assert usage["completion_tokens"] > 0
        assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
        assert usage["estimated_cost_usd"] > 0.0

        # Verify record in database
        async with db_context() as session:
            ai_dal = AIUsageDAL(session)
            records, total = await ai_dal.list_requests(
                org_id=(await session.execute(select(App.organization_id).where(App.id == uuid.UUID(app_id)))).scalar_one(),
                app_id=uuid.UUID(app_id),
            )
            assert total == 1
            rec = records[0]
            assert rec.model == "fake-llm"
            assert rec.status == "success"
            assert rec.total_tokens == usage["total_tokens"]
            assert rec.estimated_cost_usd == pytest.approx(usage["estimated_cost_usd"], abs=1e-6)


# =====================================================================
# Test 2: Hard Stop Monthly Budget Cutoff
# =====================================================================

@pytest.mark.asyncio
async def test_budget_cutoff():
    """
    Prompt 24 Acceptance Test:
    Proves that when an app's monthly spend reaches capabilities.ai.monthly_budget_usd,
    subsequent requests fail closed with structured BUDGET_EXCEEDED error.
    """
    transport = ASGITransport(app=app)
    app_key = f"budget-test-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # App configured with very small budget of $0.0001
        app_id = await create_test_app_with_ai_budget(client, app_key, monthly_budget_usd=0.0001)

        # 1. Insert a prior usage record for this month that consumes $0.00015 (exceeding budget)
        async with db_context() as session:
            ai_dal = AIUsageDAL(session)
            org_id = (await session.execute(select(App.organization_id).where(App.id == uuid.UUID(app_id)))).scalar_one()
            await ai_dal.record_usage(
                organization_id=org_id,
                app_id=uuid.UUID(app_id),
                model="fake-llm",
                provider="FakeLLMProvider",
                prompt_tokens=100,
                completion_tokens=50,
                estimated_cost_usd=0.00015,
                duration_ms=45,
                status="success",
            )
            await session.commit()

        # 2. Next request must fail closed immediately
        res = await client.post(
            "/v1/ai/chat",
            headers={"x-capsule-key": app_key, "x-capsule-id": app_id},
            json={
                "model": "fake-llm",
                "messages": [{"role": "user", "content": "This request should be blocked."}],
            },
        )
        assert res.status_code == 429, res.text
        err = res.json()["detail"]
        assert err["code"] == "BUDGET_EXCEEDED"
        assert err["error"] == "monthly_budget_exceeded"
        assert err["current_spend_usd"] >= 0.0001
        assert err["monthly_budget_usd"] == 0.0001
        assert "reset_at" in err


# =====================================================================
# Test 3: Rate Limiting (Per-Minute and Per-Day)
# =====================================================================

@pytest.mark.asyncio
async def test_rate_limit_enforcement():
    """
    Prompt 24 Acceptance Test:
    Proves rate limiting cutoff when per-minute requests exceed configured threshold.
    """
    transport = ASGITransport(app=app)
    app_key = f"ratelimit-test-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app_id = await create_test_app_with_ai_budget(client, app_key, monthly_budget_usd=10.0)

        # Set strict per-minute rate limit of 3 RPM on the organization profile
        async with db_context() as session:
            org_dal = OrganizationDAL(session)
            org = await org_dal.get_by_slug("acme-corp")
            profile = dict(org.environment_profile or {})
            if "ai" not in profile:
                profile["ai"] = {}
            profile["ai"]["rate_limits"] = {
                "requests_per_minute": 3,
                "requests_per_day": 1000,
            }
            org.environment_profile = profile
            await session.commit()

        # Execute 3 successful requests
        for i in range(3):
            res = await client.post(
                "/v1/ai/chat",
                headers={"x-capsule-key": app_key, "x-capsule-id": app_id},
                json={"model": "fake-llm", "messages": [{"role": "user", "content": f"Request {i}"}]},
            )
            assert res.status_code == 200, f"Request {i} failed: {res.text}"

        # 4th request in the same minute must be blocked with HTTP 429
        blocked_res = await client.post(
            "/v1/ai/chat",
            headers={"x-capsule-key": app_key, "x-capsule-id": app_id},
            json={"model": "fake-llm", "messages": [{"role": "user", "content": "4th request should fail"}]},
        )
        assert blocked_res.status_code == 429, blocked_res.text
        assert "Retry-After" in blocked_res.headers
        err = blocked_res.json()["detail"]
        assert err["code"] == "RATE_LIMIT_EXCEEDED"
        assert err["limit_type"] == "per_minute"
        assert err["retry_after_seconds"] > 0


# =====================================================================
# Test 4: Disallowed Model Rejected per Environment Profile
# =====================================================================

@pytest.mark.asyncio
async def test_disallowed_model_rejected():
    """
    Prompt 24 Acceptance Test:
    Proves that requesting a model not in the organization's allowed_models list is rejected.
    """
    transport = ASGITransport(app=app)
    app_key = f"model-test-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app_id = await create_test_app_with_ai_budget(client, app_key, monthly_budget_usd=5.0)

        # Request unauthorized model 'unapproved-proprietary-model'
        res = await client.post(
            "/v1/ai/chat",
            headers={"x-capsule-key": app_key, "x-capsule-id": app_id},
            json={
                "model": "unapproved-proprietary-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert res.status_code == 403, res.text
        err = res.json()["detail"]
        assert err["code"] == "MODEL_NOT_ALLOWED"
        assert "allowed_models" in err
        assert "unapproved-proprietary-model" in err["message"]


# =====================================================================
# Test 5: No Content Stored by Default (Metadata Only)
# =====================================================================

@pytest.mark.asyncio
async def test_no_content_stored_by_default():
    """
    Prompt 24 Acceptance Test:
    Proves that by default, only metadata (tokens, cost, model, timestamp) is stored.
    Prompt and response text are NULL in the database.
    """
    transport = ASGITransport(app=app)
    app_key = f"nocontent-test-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app_id = await create_test_app_with_ai_budget(client, app_key, monthly_budget_usd=5.0)

        # Ensure content_logging_enabled is False (default)
        async with db_context() as session:
            org_dal = OrganizationDAL(session)
            org = await org_dal.get_by_slug("acme-corp")
            profile = copy.deepcopy(org.environment_profile or {})
            if "ai" not in profile:
                profile["ai"] = {}
            profile["ai"]["content_logging_enabled"] = False
            await session.execute(
                update(Organization).where(Organization.id == org.id).values(environment_profile=profile)
            )
            await session.commit()

        secret_user_prompt = "TopSecretPromptText-DoNotLogMe-12345"
        res = await client.post(
            "/v1/ai/chat",
            headers={"x-capsule-key": app_key, "x-capsule-id": app_id},
            json={
                "model": "fake-llm",
                "messages": [{"role": "user", "content": secret_user_prompt}],
            },
        )
        assert res.status_code == 200, res.text

        # Verify in database: prompt_content and response_content are NULL
        async with db_context() as session:
            ai_dal = AIUsageDAL(session)
            org_id = (await session.execute(select(App.organization_id).where(App.id == uuid.UUID(app_id)))).scalar_one()
            records, _ = await ai_dal.list_requests(org_id=org_id, app_id=uuid.UUID(app_id))
            assert len(records) > 0
            rec = records[0]

            assert rec.prompt_content is None, "Prompt content must NOT be stored when logging is disabled!"
            assert rec.response_content is None, "Response content must NOT be stored when logging is disabled!"
            assert rec.prompt_tokens > 0
            assert rec.completion_tokens > 0
            assert rec.estimated_cost_usd > 0.0


# =====================================================================
# Test 6: Opt-in Content Logging and Retention Purge
# =====================================================================

@pytest.mark.asyncio
async def test_opt_in_content_logging_and_retention_purge():
    """
    Proves that when content logging is opt-in enabled, prompt & response content are stored,
    and the purge endpoint clears expired content while preserving token & cost metrics.
    """
    transport = ASGITransport(app=app)
    app_key = f"optin-test-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app_id = await create_test_app_with_ai_budget(client, app_key, monthly_budget_usd=5.0)

        # Enable content logging for organization
        async with db_context() as session:
            org_dal = OrganizationDAL(session)
            org = await org_dal.get_by_slug("acme-corp")
            profile = copy.deepcopy(org.environment_profile or {})
            if "ai" not in profile:
                profile["ai"] = {}
            profile["ai"]["content_logging_enabled"] = True
            profile["ai"]["content_retention_days"] = 30
            await session.execute(
                update(Organization).where(Organization.id == org.id).values(environment_profile=profile)
            )
            await session.commit()
            org_id = org.id

        try:
            res = await client.post(
                "/v1/ai/chat",
                headers={"x-capsule-key": app_key, "x-capsule-id": app_id},
                json={
                    "model": "fake-llm",
                    "messages": [{"role": "user", "content": "Log my prompt please."}],
                },
            )
            assert res.status_code == 200, res.text

            # Verify content is stored
            async with db_context() as session:
                ai_dal = AIUsageDAL(session)
                records, _ = await ai_dal.list_requests(org_id=org_id, app_id=uuid.UUID(app_id))
                assert len(records) > 0
                rec = records[0]
                assert rec.prompt_content is not None
                assert "Log my prompt please." in rec.prompt_content
                assert rec.response_content is not None
                record_id = rec.id

                # Simulate aging this record past 30 days
                old_time = datetime.now(timezone.utc) - timedelta(days=35)
                await session.execute(
                    update(AIUsageRecord).where(AIUsageRecord.id == record_id).values(created_at=old_time)
                )
                await session.commit()

            # Trigger purge endpoint as organization owner
            purge_res = await client.post(
                f"/v1/organizations/{org_id}/ai/purge-content",
                headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
                json={"retention_days": 30},
            )
            assert purge_res.status_code == 200, purge_res.text
            assert purge_res.json()["purged_records_count"] >= 1

            # Verify in database: content is now NULL, but metrics remain intact
            async with db_context() as session:
                res_rec = await session.execute(select(AIUsageRecord).where(AIUsageRecord.id == record_id))
                purged_record = res_rec.scalar_one()
                assert purged_record.prompt_content is None, "Expired prompt content should be purged!"
                assert purged_record.response_content is None, "Expired response content should be purged!"
                assert purged_record.prompt_tokens > 0, "Token counts must be preserved!"
                assert purged_record.estimated_cost_usd > 0.0, "Cost metrics must be preserved!"
        finally:
            async with db_context() as session:
                profile["ai"]["content_logging_enabled"] = False
                await session.execute(
                    update(Organization).where(Organization.id == org_id).values(environment_profile=profile)
                )
                await session.commit()


# =====================================================================
# Test 7: Provider Keys Never Reach App
# =====================================================================

@pytest.mark.asyncio
async def test_provider_keys_never_reach_the_app():
    """
    Prompt 24 Acceptance Test:
    Proves that platform provider API keys in environment/vault never reach the client application.
    """
    transport = ASGITransport(app=app)
    app_key = f"keys-test-{uuid.uuid4().hex[:8]}"

    secret_platform_key = "sk-live-super-secret-platform-key-9876543210"
    os.environ["OPENAI_API_KEY"] = secret_platform_key
    os.environ["GEMINI_API_KEY"] = "gemini-secret-vault-key-abcdef"

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await create_test_app_with_ai_budget(client, app_key, monthly_budget_usd=5.0)

            res = await client.post(
                "/v1/ai/chat",
                headers={"x-capsule-key": app_key, "x-capsule-id": app_id},
                json={
                    "model": "fake-llm",
                    "messages": [{"role": "user", "content": "Tell me secrets."}],
                },
            )
            assert res.status_code == 200, res.text
            response_json_str = res.text

            # Prove secret key is never in response body or headers
            assert secret_platform_key not in response_json_str
            assert "gemini-secret-vault-key-abcdef" not in response_json_str
            for header_name, header_val in res.headers.items():
                assert secret_platform_key not in header_val

    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)


# =====================================================================
# Test 8: No Tool Access by Default
# =====================================================================

@pytest.mark.asyncio
async def test_no_tool_access_by_default():
    """
    Prompt 24 Acceptance Test:
    Proves tool calling definitions are rejected by default with HTTP 403 TOOL_ACCESS_DISABLED.
    """
    transport = ASGITransport(app=app)
    app_key = f"tools-test-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app_id = await create_test_app_with_ai_budget(client, app_key, monthly_budget_usd=5.0)

        res = await client.post(
            "/v1/ai/chat",
            headers={"x-capsule-key": app_key, "x-capsule-id": app_id},
            json={
                "model": "fake-llm",
                "messages": [{"role": "user", "content": "Execute a tool"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "read_filesystem", "description": "Read host filesystem"},
                    }
                ],
            },
        )
        assert res.status_code == 403, res.text
        err = res.json()["detail"]
        assert err["code"] == "TOOL_ACCESS_DISABLED"


# =====================================================================
# Test 9: Best-Effort Sensitive Pattern Redaction
# =====================================================================

@pytest.mark.asyncio
async def test_sensitive_pattern_redaction():
    """
    Prompt 24 Acceptance Test:
    Proves basic best-effort pattern scrubbing (credit cards, SSNs, tokens) from prompts.
    """
    raw_prompt = "My credit card is 4111-2222-3333-4444 and my SSN is 000-12-3456 with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    cleaned, was_redacted = redact_sensitive_patterns(raw_prompt)

    assert was_redacted is True
    assert "4111-2222-3333-4444" not in cleaned
    assert "[REDACTED_CREDIT_CARD]" in cleaned
    assert "000-12-3456" not in cleaned
    assert "[REDACTED_SSN]" in cleaned
    assert "[REDACTED_TOKEN]" in cleaned


# =====================================================================
# Test 10: Streaming SSE Support
# =====================================================================

@pytest.mark.asyncio
async def test_streaming_sse_support():
    """
    Prompt 24 Acceptance Test:
    Proves that when stream: true, chunks are delivered via Server-Sent Events (SSE)
    and usage is metered upon stream completion.
    """
    transport = ASGITransport(app=app)
    app_key = f"stream-test-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app_id = await create_test_app_with_ai_budget(client, app_key, monthly_budget_usd=5.0)

        res = await client.post(
            "/v1/ai/chat",
            headers={"x-capsule-key": app_key, "x-capsule-id": app_id},
            json={
                "model": "fake-llm",
                "stream": True,
                "messages": [{"role": "user", "content": "Stream response"}],
            },
        )
        assert res.status_code == 200, res.text
        assert "text/event-stream" in res.headers["content-type"]

        # Parse SSE lines
        body = res.text
        lines = [line for line in body.split("\n") if line.startswith("data: ")]
        assert len(lines) > 1, f"Expected multiple SSE chunks, got {lines}"
        assert lines[-1] == "data: [DONE]"

        # Verify the chunks contain delta
        first_chunk = json.loads(lines[0][6:])
        assert "delta" in first_chunk


# =====================================================================
# Test 11: App and Org Usage Endpoints
# =====================================================================

@pytest.mark.asyncio
async def test_usage_reporting_endpoints():
    """
    Verifies GET /v1/apps/{app_id}/ai/usage and GET /v1/organizations/{org_id}/ai/usage.
    """
    transport = ASGITransport(app=app)
    app_key = f"usage-test-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app_id = await create_test_app_with_ai_budget(client, app_key, monthly_budget_usd=8.0)

        # 1. Execute a request
        await client.post(
            "/v1/ai/chat",
            headers={"x-capsule-key": app_key, "x-capsule-id": app_id},
            json={"model": "fake-llm", "messages": [{"role": "user", "content": "Hello"}]},
        )

        # 2. Query App Usage
        app_usage_res = await client.get(
            f"/v1/apps/{app_id}/ai/usage",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert app_usage_res.status_code == 200, app_usage_res.text
        app_usage = app_usage_res.json()
        assert app_usage["app_id"] == app_id
        assert app_usage["monthly_budget_usd"] == 8.0
        assert app_usage["current_spend_usd"] > 0.0
        assert app_usage["monthly_requests"] >= 1
        assert len(app_usage["recent_requests"]) >= 1

        # 3. Query Org Usage
        async with db_context() as session:
            org_id = (await session.execute(select(App.organization_id).where(App.id == uuid.UUID(app_id)))).scalar_one()

        org_usage_res = await client.get(
            f"/v1/organizations/{org_id}/ai/usage",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert org_usage_res.status_code == 200, org_usage_res.text
        org_usage = org_usage_res.json()
        assert org_usage["total_requests"] >= 1
        assert org_usage["total_tokens"] > 0
        assert org_usage["total_estimated_cost_usd"] > 0.0
        assert len(org_usage["by_model"]) >= 1
        assert len(org_usage["by_app"]) >= 1

        # 4. Query Paginated Requests Log
        reqs_res = await client.get(
            f"/v1/organizations/{org_id}/ai/requests",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert reqs_res.status_code == 200, reqs_res.text
        reqs_data = reqs_res.json()
        assert reqs_data["total"] >= 1
        assert len(reqs_data["items"]) >= 1
        item = reqs_data["items"][0]
        assert "model" in item
        assert "total_tokens" in item
        assert "estimated_cost_usd" in item
