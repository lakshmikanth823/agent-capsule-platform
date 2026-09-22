"""
Comprehensive Test Suite for Environment Profiles & Policy Ceiling (Prompt 17)

Fulfills PRD FR-027, FR-028, FR-032:
- Manifest cannot widen policy (runtime, shape, quotas, connectors, egress)
- Structured policy violations
- GET /v1/apps/{id}/effective-policy
- Conditional approval (small personal apps deploy automatically, service identity requires approval)
- Agent publish token self-approval prohibited
- Admin API: preview diff and profile update
- App re-evaluation & grace period enforcement
"""
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from storage import get_storage_driver
from db.session import db_context
from db.dal import OrganizationDAL, AppDAL, AuditDAL

MOCK_ALICE_TOKEN = "mock-alice-token"  # Owner of Acme Corp
MOCK_BOB_TOKEN = "mock-bob-token"      # Member/User in Acme Corp

BASE_MANIFEST = {
    "apiVersion": "capsule/v1alpha1",
    "name": "Profile Test App",
    "shape": "web-app",
    "runtime": "node22",
    "roles": ["employee"],
    "capabilities": {
        "db": {"type": "sqlite"},
        "identity": True,
    },
    "egress": [],
    "sharing": {"default": "org"},
    "limits": {
        "cpu": "small",
        "memory_mb": 256,
        "request_timeout_s": 30,
        "db_max_mb": 50,
        "blob_max_mb": 200,
    },
}


@pytest.mark.asyncio
async def test_manifest_cannot_widen_runtime_or_shape():
    """Policy ceiling: Attempting to request unallowed shape or runtime fails with structured POLICY_VIOLATION."""
    transport = ASGITransport(app=app)
    app_key = f"app-widen-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unallowed runtime: python3
        bad_runtime_manifest = {**BASE_MANIFEST, "id": app_key, "runtime": "python3"}
        res1 = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Bad Runtime App",
                "shape": "web-app",
                "runtime": "python3",
                "manifest": bad_runtime_manifest,
            },
        )
        assert res1.status_code == 422, res1.text
        assert "runtime" in res1.text.lower()

        # 2. Unallowed shape: background-worker
        app_key2 = f"app-widen2-{uuid.uuid4().hex[:8]}"
        bad_shape_manifest = {**BASE_MANIFEST, "id": app_key2, "shape": "background-worker"}
        res2 = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key2,
                "name": "Bad Shape App",
                "shape": "background-worker",
                "runtime": "node22",
                "manifest": bad_shape_manifest,
            },
        )
        assert res2.status_code == 422, res2.text
        assert "shape" in res2.text.lower()


@pytest.mark.asyncio
async def test_manifest_cannot_widen_resource_quotas():
    """Policy ceiling: Requesting memory beyond profile ceiling fails with POLICY_VIOLATION."""
    transport = ASGITransport(app=app)
    app_key = f"app-quota-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Update org profile ceiling to max_memory_mb = 200
        await client.put(
            "/v1/organizations/acme-corp/environment-profile",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"profile": {"quotas": {"max_memory_mb": 200, "apps_per_user": 200}}},
        )

        # 2. Manifest requests 256MB (valid for manifest-schema, but exceeds org ceiling 200MB)
        manifest = {
            **BASE_MANIFEST,
            "id": app_key,
            "limits": {
                **BASE_MANIFEST["limits"],
                "memory_mb": 256,
            },
        }

        res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "High Memory App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert res.status_code == 422, res.text
        detail = res.json().get("detail", {})
        assert detail.get("code") == "POLICY_VIOLATION"
        assert detail.get("error") == "quota_ceiling_exceeded"
        assert "memory_mb" in detail.get("field", "")

        # Restore ceiling
        await client.put(
            "/v1/organizations/acme-corp/environment-profile",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"profile": {"quotas": {"max_memory_mb": 512, "apps_per_user": 200}}},
        )


@pytest.mark.asyncio
async def test_egress_denylist_enforcement():
    """Policy ceiling: Declaring egress to internal/metadata addresses is rejected."""
    transport = ASGITransport(app=app)
    app_key = f"app-egress-{uuid.uuid4().hex[:8]}"
    manifest = {
        **BASE_MANIFEST,
        "id": app_key,
        "egress": ["db.internal"],  # FQDN matching *.internal denylist
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "SSRF Egress App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert res.status_code == 422, res.text
        detail = res.json().get("detail", {})
        assert detail.get("code") == "POLICY_VIOLATION"
        assert detail.get("error") == "egress_domain_denied"


@pytest.mark.asyncio
async def test_manifest_cannot_widen_connectors_or_capabilities():
    """Policy ceiling: Requesting forbidden connectors or unallowed identity modes is rejected."""
    transport = ASGITransport(app=app)
    app_key = f"app-conn-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Update org profile: allow only slack.post and fake.echo; disallow service identity
        await client.put(
            "/v1/organizations/acme-corp/environment-profile",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "profile": {
                    "quotas": {"apps_per_user": 200},
                    "capabilities": {
                        "connectors": {
                            "allowed_connectors": ["slack.post", "fake.echo"],
                            "allow_service_identity": False,
                        }
                    }
                }
            },
        )

        # 2. Manifest requests stripe.charge (not allowed)
        bad_conn_manifest = {
            **BASE_MANIFEST,
            "id": app_key,
            "capabilities": {
                **BASE_MANIFEST["capabilities"],
                "connectors": [{"name": "stripe.charge", "acts_as": "viewer"}],
            },
        }

        res1 = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Disallowed Connector App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": bad_conn_manifest,
            },
        )
        assert res1.status_code == 422, res1.text
        detail1 = res1.json().get("detail", {})
        assert detail1.get("code") == "POLICY_VIOLATION"
        assert detail1.get("error") == "connector_not_allowed"
        assert "stripe.charge" in detail1.get("message", "")

        # 3. Manifest requests service identity when allow_service_identity is False
        app_key2 = f"app-conn2-{uuid.uuid4().hex[:8]}"
        bad_ident_manifest = {
            **BASE_MANIFEST,
            "id": app_key2,
            "capabilities": {
                **BASE_MANIFEST["capabilities"],
                "connectors": [{"name": "slack.post", "acts_as": "service"}],
            },
        }
        res2 = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key2,
                "name": "Disallowed Service Identity App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": bad_ident_manifest,
            },
        )
        assert res2.status_code == 422, res2.text
        detail2 = res2.json().get("detail", {})
        assert detail2.get("code") == "POLICY_VIOLATION"
        assert detail2.get("error") == "service_identity_prohibited"

        # Restore profile
        await client.put(
            "/v1/organizations/acme-corp/environment-profile",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "profile": {
                    "quotas": {"apps_per_user": 200},
                    "capabilities": {
                        "connectors": {
                            "allowed_connectors": ["*"],
                            "allow_service_identity": True,
                        }
                    }
                }
            },
        )


@pytest.mark.asyncio
async def test_get_effective_policy_endpoint():
    """GET /v1/apps/{id}/effective-policy returns computed ceiling and effective policy."""
    transport = ASGITransport(app=app)
    app_key = f"app-eff-{uuid.uuid4().hex[:8]}"
    manifest = {**BASE_MANIFEST, "id": app_key}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create app
        create_res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Effective Policy App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert create_res.status_code == 201, create_res.text
        app_id = create_res.json()["id"]

        # Call effective-policy
        eff_res = await client.get(
            f"/v1/apps/{app_id}/effective-policy",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert eff_res.status_code == 200, eff_res.text
        data = eff_res.json()
        assert data["app_key"] == app_key
        assert data["is_compliant"] is True
        assert "effective_policy" in data
        assert "profile_ceiling" in data
        assert data["effective_policy"]["limits"]["memory_mb"] == 256
        assert data["profile_ceiling"]["quotas"]["max_memory_mb"] == 512


@pytest.mark.asyncio
async def test_conditional_approval_small_personal_app_fast_path():
    """FR-032: Small personal app (viewer only, audience <= threshold) deploys automatically."""
    transport = ASGITransport(app=app)
    app_key = f"app-fast-{uuid.uuid4().hex[:8]}"
    manifest = {
        **BASE_MANIFEST,
        "id": app_key,
        "sharing": {"default": "org"},  # Personal app
        "capabilities": {
            "db": {"type": "sqlite"},
            "identity": True,
            "connectors": [{"name": "slack.post", "acts_as": "viewer"}],
        },
    }

    storage = get_storage_driver()
    artifact_ref = f"artifacts/{app_key}.tar.gz"
    await storage.put(artifact_ref, b"bundle contents")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Fast Path App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert create_res.status_code == 201
        app_id = create_res.json()["id"]

        # Publish
        pub_res = await client.post(
            f"/v1/apps/{app_id}/publish",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "manifest": manifest,
                "artifact": {"ref": artifact_ref, "sha256": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"},
                "change_description": "Initial fast-path release",
            },
        )
        assert pub_res.status_code == 202, pub_res.text
        pub_data = pub_res.json()
        assert pub_data["status"] == "succeeded"

        # Verify app is active
        app_res = await client.get(
            f"/v1/apps/{app_id}",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert app_res.json()["status"] == "active"


@pytest.mark.asyncio
async def test_publish_token_cannot_approve_escalation():
    """FR-032: An agent's scoped publish token can NEVER approve capability escalation."""
    transport = ASGITransport(app=app)
    app_key = f"app-no-self-{uuid.uuid4().hex[:8]}"

    # Step 1: Create app and token
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "No Self Approval App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": {**BASE_MANIFEST, "id": app_key},
            },
        )
        assert create_res.status_code == 201
        app_id = create_res.json()["id"]

        # Mint publish token
        tok_res = await client.post(
            "/v1/tokens/publish",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"app_id": app_id, "expires_in_seconds": 3600},
        )
        assert tok_res.status_code == 200
        publish_token = tok_res.json()["token"]

        # Attempt to call approvals decision endpoint using the publish token -> MUST return 403 Forbidden
        dummy_approval_id = uuid.uuid4()
        approve_res = await client.post(
            f"/v1/apps/{app_id}/approvals/{dummy_approval_id}/approve",
            headers={"Authorization": f"Bearer {publish_token}"},
        )
        assert approve_res.status_code == 403, approve_res.text
        assert "publish credential" in approve_res.json()["detail"]["message"].lower()


@pytest.mark.asyncio
async def test_admin_profile_update_diff_preview_and_reevaluation():
    """Admin API: preview-diff shows changes, PUT updates profile, re-evaluates apps and enforces grace period."""
    transport = ASGITransport(app=app)
    app_key = f"app-reeval-{uuid.uuid4().hex[:8]}"

    # Manifest requesting 300MB memory (allowed under default max 512MB)
    manifest = {
        **BASE_MANIFEST,
        "id": app_key,
        "limits": {**BASE_MANIFEST["limits"], "memory_mb": 300},
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create app
        create_res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Re-eval Test App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert create_res.status_code == 201
        app_id = create_res.json()["id"]

        # 2. Preview Diff: Tighten max_memory_mb to 200MB (making this app non-compliant)
        preview_res = await client.post(
            "/v1/organizations/acme-corp/environment-profile/preview-diff",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "profile": {
                    "quotas": {"max_memory_mb": 200},
                }
            },
        )
        assert preview_res.status_code == 200, preview_res.text
        preview_data = preview_res.json()
        assert preview_data["diff"]["has_changes"] is True
        assert preview_data["impacted_apps_count"] >= 1
        assert any(a["app_key"] == app_key for a in preview_data["impacted_apps"])

        # 3. Non-admin Bob cannot update profile -> 403
        bad_put = await client.put(
            "/v1/organizations/acme-corp/environment-profile",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
            json={"profile": {"quotas": {"max_memory_mb": 200}}},
        )
        assert bad_put.status_code == 403

        # 4. Admin Alice updates profile with grace_period_hours = 0, action = suspend
        put_res = await client.put(
            "/v1/organizations/acme-corp/environment-profile",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "profile": {
                    "quotas": {"max_memory_mb": 200, "apps_per_user": 200},
                    "compliance": {"grace_period_hours": 0, "enforcement_action": "suspend"},
                }
            },
        )
        assert put_res.status_code == 200, put_res.text
        put_data = put_res.json()
        assert put_data["status"] == "updated"
        assert put_data["re_evaluation"]["non_compliant_apps_count"] >= 1

        # 5. Verify the app was suspended because grace_period == 0
        app_res = await client.get(
            f"/v1/apps/{app_id}",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert app_res.json()["status"] == "suspended"

        # 6. Verify audit event was logged
        audit_res = await client.get(
            "/v1/audit/events?action=organization.environment_profile_updated",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert audit_res.status_code == 200
        events = audit_res.json()
        assert len(events) >= 1

        # Restore profile for subsequent tests
        await client.put(
            "/v1/organizations/acme-corp/environment-profile",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "profile": {
                    "quotas": {"max_memory_mb": 512, "apps_per_user": 200},
                    "compliance": {"grace_period_hours": 72, "enforcement_action": "restrict"},
                }
            },
        )
