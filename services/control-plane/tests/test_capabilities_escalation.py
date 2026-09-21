"""
Tests for Capability Escalation on Update (Prompt 13).
Verifies:
- Normal updates deploy without approval.
- New/broadened capabilities or egress are held in pending_approval.
- Publish credentials CANNOT approve their own escalation (Security Invariant).
- Regular users cannot approve.
- App Owner can approve, which activates the version.
"""
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from storage import get_storage_driver

MOCK_ALICE_TOKEN = "mock-alice-token"  # Owner
MOCK_BOB_TOKEN = "mock-bob-token"      # Regular User


@pytest.mark.asyncio
async def test_capability_escalation_lifecycle():
    transport = ASGITransport(app=app)
    app_key = f"escalation-{uuid.uuid4().hex[:8]}"
    storage = get_storage_driver()

    # Pre-seed artifacts in storage
    await storage.put(f"capsules/{app_key}/artifacts/v1.tar.gz", b"bundle v1")
    await storage.put(f"capsules/{app_key}/artifacts/v2.tar.gz", b"bundle v2")
    await storage.put(f"capsules/{app_key}/artifacts/v3.tar.gz", b"bundle v3")

    base_manifest = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": "Escalation Test App",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["employee"],
        "capabilities": {"db": {"type": "sqlite"}},
        "egress": [],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create App
        create_res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Escalation Test App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": base_manifest,
            },
        )
        assert create_res.status_code == 201, create_res.text
        app_data = create_res.json()
        app_id = app_data["id"]

        # 2. Publish Version 1 (Baseline)
        pub1_res = await client.post(
            f"/v1/apps/{app_key}/publish",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "manifest": base_manifest,
                "artifact": {"ref": f"capsules/{app_key}/artifacts/v1.tar.gz", "sha256": "abc123"},
                "change_description": "Initial baseline release",
            },
        )
        assert pub1_res.status_code == 202, pub1_res.text
        assert pub1_res.json()["status"] == "succeeded"
        v1_id = pub1_res.json()["version_id"]

        # Verify app current_version is v1
        app_res = await client.get(f"/v1/apps/{app_key}", headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"})
        assert app_res.json()["current_version_id"] == v1_id

        # 3. Publish Version 2: Normal update with NO capability changes
        pub2_res = await client.post(
            f"/v1/apps/{app_key}/publish",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "manifest": base_manifest,
                "artifact": {"ref": f"capsules/{app_key}/artifacts/v2.tar.gz", "sha256": "def456"},
                "change_description": "Bug fix update without capability changes",
            },
        )
        assert pub2_res.status_code == 202, pub2_res.text
        assert pub2_res.json()["status"] == "succeeded"
        v2_id = pub2_res.json()["version_id"]

        # Verify app current_version is now v2
        app_res2 = await client.get(f"/v1/apps/{app_key}", headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"})
        assert app_res2.json()["current_version_id"] == v2_id

        # 4. Issue a scoped publish token to simulate an AI agent / CI publish
        token_res = await client.post(
            "/v1/tokens/publish",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"app_id": app_id, "scope": "app:publish", "expires_in_seconds": 3600},
        )
        assert token_res.status_code == 200
        publish_token = token_res.json()["token"]

        # 5. Publish Version 3: Escalated update adding NEW egress domain and AI capability!
        escalated_manifest = {
            **base_manifest,
            "capabilities": {
                "db": {"type": "sqlite"},
                "ai": {"monthly_budget_usd": 5},  # NEW CAPABILITY!
            },
            "egress": ["api.slack.com"],  # NEW EGRESS!
        }

        pub3_res = await client.post(
            f"/v1/apps/{app_key}/publish",
            headers={"Authorization": f"Bearer {publish_token}"},
            json={
                "manifest": escalated_manifest,
                "artifact": {"ref": f"capsules/{app_key}/artifacts/v3.tar.gz", "sha256": "ghi789"},
                "change_description": "Feature update adding Slack egress and AI capability",
            },
        )
        assert pub3_res.status_code == 202, pub3_res.text
        pub3_data = pub3_res.json()
        assert pub3_data["status"] == "pending_approval"
        assert len(pub3_data["errors"]) > 0
        v3_id = pub3_data["version_id"]

        # Verify app current_version is STILL v2 (deployment was held!)
        app_res3 = await client.get(f"/v1/apps/{app_key}", headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"})
        assert app_res3.json()["current_version_id"] == v2_id

        # 6. List approvals
        approvals_res = await client.get(
            f"/v1/apps/{app_key}/approvals",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert approvals_res.status_code == 200
        approvals = approvals_res.json()["approvals"]
        assert len(approvals) >= 2  # Egress and AI capability
        approval_ids = [a["id"] for a in approvals if a["status"] == "pending"]
        assert len(approval_ids) >= 2

        # 7. SECURITY INVARIANT: Publish Token CANNOT approve its own escalation
        self_approve_res = await client.post(
            f"/v1/apps/{app_key}/approvals/{approval_ids[0]}/approve",
            headers={"Authorization": f"Bearer {publish_token}"},
        )
        assert self_approve_res.status_code == 403
        assert self_approve_res.json()["detail"]["code"] == "FORBIDDEN"
        assert "A publish credential can never approve" in self_approve_res.json()["detail"]["message"]

        # 8. Regular User (Bob) CANNOT approve
        bob_approve_res = await client.post(
            f"/v1/apps/{app_key}/approvals/{approval_ids[0]}/approve",
            headers={"Authorization": f"Bearer {MOCK_BOB_TOKEN}"},
        )
        assert bob_approve_res.status_code == 403
        assert bob_approve_res.json()["detail"]["code"] == "FORBIDDEN"

        # 9. Owner (Alice) approves all pending approvals
        for aid in approval_ids:
            apprv_res = await client.post(
                f"/v1/apps/{app_key}/approvals/{aid}/approve",
                headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            )
            assert apprv_res.status_code == 200
            assert apprv_res.json()["status"] == "approved"

        # Verify that once all are approved, v3 is activated as current_version!
        app_res_final = await client.get(f"/v1/apps/{app_key}", headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"})
        assert app_res_final.json()["current_version_id"] == v3_id
        assert app_res_final.json()["status"] == "active"
