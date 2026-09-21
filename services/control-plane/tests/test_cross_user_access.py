"""
Tests for cross-user and cross-organization isolation and publish token scoping.
"""
import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from main import app
from storage import get_storage_driver

VALID_MANIFEST = {
    "apiVersion": "capsule/v1alpha1",
    "id": "survey-app",
    "name": "Survey Application",
    "shape": "web-app",
    "runtime": "node22",
    "roles": ["admin"],
    "capabilities": {},
    "egress": [],
    "sharing": {"default": "org"},
    "limits": {
        "cpu": "small",
        "memory_mb": 256,
        "request_timeout_s": 30,
    },
}


@pytest.mark.asyncio
async def test_cross_org_isolation():
    transport = ASGITransport(app=app)
    alice_app_key = f"alice-{uuid.uuid4().hex[:8]}"
    storage = get_storage_driver()
    artifact_ref = f"artifacts/{alice_app_key}.tar.gz"
    await storage.put(artifact_ref, b"bundle contents")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Alice creates an app in Acme Corp
        resp_alice_create = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": alice_app_key,
                "name": "Alice App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": {**VALID_MANIFEST, "id": alice_app_key},
            },
        )
        assert resp_alice_create.status_code == 201
        alice_app_id = resp_alice_create.json()["id"]

        # 2. Charlie (Other Corp) tries to GET Alice's app -> 404
        resp_charlie_get = await client.get(
            f"/v1/apps/{alice_app_id}",
            headers={"Authorization": "Bearer mock-charlie-token"},
        )
        assert resp_charlie_get.status_code == 404

        # 3. Charlie tries to PUBLISH to Alice's app -> 404
        resp_charlie_pub = await client.post(
            f"/v1/apps/{alice_app_id}/publish",
            headers={"Authorization": "Bearer mock-charlie-token"},
            json={
                "manifest": {**VALID_MANIFEST, "id": alice_app_key},
                "artifact": {"ref": artifact_ref},
            },
        )
        assert resp_charlie_pub.status_code == 404

        # 4. Charlie lists apps -> Alice's app is not present
        resp_charlie_list = await client.get(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-charlie-token"},
        )
        assert resp_charlie_list.status_code == 200
        charlie_apps = resp_charlie_list.json()["items"]
        assert not any(a["id"] == alice_app_id for a in charlie_apps)


@pytest.mark.asyncio
async def test_scoped_publish_token_enforcement():
    transport = ASGITransport(app=app)
    app1_key = f"app1-{uuid.uuid4().hex[:8]}"
    app2_key = f"app2-{uuid.uuid4().hex[:8]}"
    storage = get_storage_driver()
    await storage.put(f"artifacts/{app1_key}.tar.gz", b"app 1")
    await storage.put(f"artifacts/{app2_key}.tar.gz", b"app 2")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create App 1 and App 2
        resp1 = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": app1_key,
                "name": "App 1",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": {**VALID_MANIFEST, "id": app1_key},
            },
        )
        assert resp1.status_code == 201
        app1_id = resp1.json()["id"]

        resp2 = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": app2_key,
                "name": "App 2",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": {**VALID_MANIFEST, "id": app2_key},
            },
        )
        assert resp2.status_code == 201
        app2_id = resp2.json()["id"]

        # Issue publish token scoped strictly to App 1
        resp_token = await client.post(
            "/v1/tokens/publish",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={"app_id": app1_id, "expires_in_seconds": 3600},
        )
        assert resp_token.status_code == 200
        app1_token = resp_token.json()["token"]

        # Publish to App 1 with App 1 token -> 202
        resp_pub1 = await client.post(
            f"/v1/apps/{app1_id}/publish",
            headers={"Authorization": f"Bearer {app1_token}"},
            json={
                "manifest": {**VALID_MANIFEST, "id": app1_key},
                "artifact": {"ref": f"artifacts/{app1_key}.tar.gz"},
            },
        )
        assert resp_pub1.status_code == 202

        # Publish to App 2 with App 1 token -> 403 Forbidden
        resp_pub2 = await client.post(
            f"/v1/apps/{app2_id}/publish",
            headers={"Authorization": f"Bearer {app1_token}"},
            json={
                "manifest": {**VALID_MANIFEST, "id": app2_key},
                "artifact": {"ref": f"artifacts/{app2_key}.tar.gz"},
            },
        )
        assert resp_pub2.status_code == 403
        assert resp_pub2.json()["detail"]["code"] == "FORBIDDEN"
