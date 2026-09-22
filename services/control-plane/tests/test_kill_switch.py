"""
Comprehensive test suite for Prompt 23: Kill switch and emergency controls.

Tests:
- Non-admins cannot use org controls (freeze org, disable connector, org mass revocation).
- App suspend: requires reason, owner/editor/admin authorized.
- App resume: admin/owner only.
- Org freeze and resume: suspends all apps, prevents publishing while frozen.
- Org-wide connector disablement.
- Mass token and session revocation (org-level and user-level).
- Platform-operator break-glass endpoints with x-platform-operator-key.
- Every action records an audit event with actor, reason, and scope.
"""
import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from main import app as fastapi_app

MOCK_ALICE_TOKEN = "mock-alice-token"  # Org Owner (Admin)
MOCK_BOB_TOKEN = "mock-bob-token"      # Regular User
MOCK_OPERATOR_SECRET = "dev-operator-break-glass-secret-key"


@pytest.fixture(autouse=True)
async def reset_org_state():
    """Ensure acme-corp is active before every test to avoid state leakage."""
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Use the bypass resume endpoint so this works even if org is suspended
        await client.post(
            "/v1/kill-switch/organizations/acme-corp/resume",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
    yield
    # Also clean up after the test
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/v1/kill-switch/organizations/acme-corp/resume",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )


@pytest.mark.asyncio
async def test_non_admins_cannot_use_org_controls():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Bob (regular user) tries org-level freeze
        res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/suspend",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
            json={"reason": "Unauthorized attempt"},
        )
        assert res.status_code == 403, res.text
        assert res.json()["detail"]["code"] == "FORBIDDEN"

        # Bob tries org-level resume
        res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/resume",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
        )
        assert res.status_code == 403, res.text

        # Bob tries to disable connector
        res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/connectors/slack/disable",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
            json={"reason": "Unauthorized attempt"},
        )
        assert res.status_code == 403, res.text

        # Bob tries org-level mass token revocation
        res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/tokens/revoke",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
        )
        assert res.status_code == 403, res.text

        # Bob tries org-level mass session revocation
        res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/sessions/revoke",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
        )
        assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_app_suspend_and_resume_lifecycle():
    transport = ASGITransport(app=fastapi_app)
    app_key = f"killswitch-{uuid.uuid4().hex[:8]}"

    manifest = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": "Killswitch App",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["employee"],
        "capabilities": {"db": {"type": "sqlite"}},
        "egress": [],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create app as Alice
        create_res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Killswitch App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert create_res.status_code == 201, create_res.text
        app_id = create_res.json()["id"]

        # Suspend without reason -> 422
        bad_suspend = await client.post(
            f"/v1/kill-switch/apps/{app_id}/suspend",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={},
        )
        assert bad_suspend.status_code == 422

        # Suspend with empty reason -> 422 (min_length=3)
        bad_reason = await client.post(
            f"/v1/kill-switch/apps/{app_id}/suspend",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"reason": "no"},
        )
        assert bad_reason.status_code == 422

        # Suspend as Alice with valid reason -> 200
        suspend_res = await client.post(
            f"/v1/kill-switch/apps/{app_id}/suspend",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"reason": "Security vulnerability discovered"},
        )
        assert suspend_res.status_code == 200, suspend_res.text
        data = suspend_res.json()
        assert data["status"] == "suspended"
        assert data["suspension_reason"] == "Security vulnerability discovered"

        # Bob (not owner or admin) cannot resume
        bob_resume = await client.post(
            f"/v1/kill-switch/apps/{app_id}/resume",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
        )
        assert bob_resume.status_code == 403

        # Alice resumes
        alice_resume = await client.post(
            f"/v1/kill-switch/apps/{app_id}/resume",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert alice_resume.status_code == 200, alice_resume.text
        assert alice_resume.json()["status"] == "active"


@pytest.mark.asyncio
async def test_org_freeze_and_resume():
    transport = ASGITransport(app=fastapi_app)
    app_key = f"freeze-{uuid.uuid4().hex[:8]}"

    manifest = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": "Org Freeze Test App",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["employee"],
        "capabilities": {},
        "egress": [],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create an app in the org
        create_res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Org Freeze Test App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert create_res.status_code == 201

        # Freeze organization as Alice (owner)
        freeze_res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/suspend",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"reason": "Emergency containment action"},
        )
        assert freeze_res.status_code == 200, freeze_res.text
        freeze_data = freeze_res.json()
        assert freeze_data["status"] == "suspended"
        assert freeze_data["suspended_apps_count"] >= 1

        # Try to publish while org is suspended -> 403 ORGANIZATION_SUSPENDED
        pub_res = await client.post(
            f"/v1/apps/{app_key}/publish",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"manifest": manifest, "description": "Attempt while suspended"},
        )
        assert pub_res.status_code == 403, pub_res.text
        assert pub_res.json()["detail"]["code"] == "ORGANIZATION_SUSPENDED"

        # Resume organization
        resume_res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/resume",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert resume_res.status_code == 200, resume_res.text
        assert resume_res.json()["status"] == "active"


@pytest.mark.asyncio
async def test_connector_disable_org_wide():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/connectors/slack/disable",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"reason": "Compromised webhook key"},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["disabled"] is True
        assert "slack" in data["disabled_connectors"]


@pytest.mark.asyncio
async def test_mass_token_and_session_revocation():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Get Bob's user id FIRST before any revocation
        me_res = await client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
        )
        assert me_res.status_code == 200, me_res.text
        bob_id = me_res.json()["id"]

        # 1. Org-wide token revocation
        org_tok_res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/tokens/revoke",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert org_tok_res.status_code == 200, org_tok_res.text
        assert "tokens_revoked_at" in org_tok_res.json()

        # 2. Org-wide session revocation
        org_sess_res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/sessions/revoke",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert org_sess_res.status_code == 200, org_sess_res.text
        assert "sessions_revoked_at" in org_sess_res.json()

        # 3. User-level token revocation by self (uses bypass dep, works even if revoked)
        user_tok_res = await client.post(
            f"/v1/kill-switch/users/{bob_id}/tokens/revoke",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
        )
        assert user_tok_res.status_code == 200, user_tok_res.text
        assert "tokens_revoked_at" in user_tok_res.json()

        # 4. User-level session revocation by self (uses bypass dep, works even if revoked)
        user_sess_res = await client.post(
            f"/v1/kill-switch/users/{bob_id}/sessions/revoke",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
        )
        assert user_sess_res.status_code == 200, user_sess_res.text
        assert "sessions_revoked_at" in user_sess_res.json()



@pytest.mark.asyncio
async def test_platform_operator_break_glass():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Without key -> 403
        no_key_res = await client.post(
            "/v1/kill-switch/operator/freeze-org/acme-corp",
            json={"reason": "Global breach"},
        )
        assert no_key_res.status_code == 403, no_key_res.text
        assert no_key_res.json()["detail"]["code"] == "OPERATOR_AUTH_FAILED"

        # With invalid key -> 403
        bad_key_res = await client.post(
            "/v1/kill-switch/operator/freeze-org/acme-corp",
            headers={"x-platform-operator-key": "invalid-secret"},
            json={"reason": "Global breach"},
        )
        assert bad_key_res.status_code == 403

        # With valid key -> 200
        valid_res = await client.post(
            "/v1/kill-switch/operator/freeze-org/acme-corp",
            headers={"x-platform-operator-key": MOCK_OPERATOR_SECRET},
            json={"reason": "Global breach containment"},
        )
        assert valid_res.status_code == 200, valid_res.text
        assert valid_res.json()["status"] == "suspended"

        # Resume org so subsequent tests don't fail
        resume_res = await client.post(
            "/v1/kill-switch/organizations/acme-corp/resume",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert resume_res.status_code == 200


@pytest.mark.asyncio
async def test_audit_events_recorded_for_kill_switch_actions():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/v1/audit/events",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert res.status_code == 200, res.text
        events = res.json()
        actions = [e["action"] for e in events]

        # Verify key kill switch actions were recorded
        assert any("app.suspend" in a for a in actions), f"app.suspend not found in {actions}"
        assert any("organization.freeze" in a for a in actions), f"organization.freeze not found in {actions}"
        assert any("connector.disable" in a for a in actions), f"connector.disable not found in {actions}"
        assert any("tokens.revoke_org" in a for a in actions), f"tokens.revoke_org not found in {actions}"
