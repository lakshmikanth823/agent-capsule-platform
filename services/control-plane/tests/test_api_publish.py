"""
Tests for Publish API endpoint, idempotency, version management, and audit events.
"""
import pytest
import uuid
import json
from httpx import AsyncClient, ASGITransport
from main import app
from storage import get_storage_driver

VALID_MANIFEST = {
    "apiVersion": "capsule/v1alpha1",
    "id": "survey-app",
    "name": "Survey Application",
    "shape": "web-app",
    "runtime": "node22",
    "roles": ["admin", "respondent"],
    "capabilities": {
        "db": {
            "type": "sqlite",
        },
    },
    "egress": [],
    "sharing": {"default": "org"},
    "limits": {
        "cpu": "small",
        "memory_mb": 256,
        "request_timeout_s": 30,
    },
}


@pytest.mark.asyncio
async def test_publish_flow_and_idempotency():
    transport = ASGITransport(app=app)
    app_key = f"app-{uuid.uuid4().hex[:8]}"
    manifest = {**VALID_MANIFEST, "id": app_key}
    storage = get_storage_driver()

    # Pre-seed a dummy artifact bundle in storage
    artifact_ref = f"artifacts/{app_key}.tar.gz"
    await storage.put(artifact_ref, b"fake bundle tar contents")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create app
        resp_create = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": app_key,
                "name": "Test App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert resp_create.status_code == 201
        app_id = resp_create.json()["id"]

        # 2. Publish Version 1 with Idempotency Key
        idempotency_key = f"key-{uuid.uuid4().hex}-{uuid.uuid4().hex}"
        publish_payload = {
            "manifest": manifest,
            "artifact": {"ref": artifact_ref, "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"},
            "change_description": "Initial publish",
        }
        resp_pub1 = await client.post(
            f"/v1/apps/{app_id}/publish",
            headers={
                "Authorization": "Bearer mock-alice-token",
                "Idempotency-Key": idempotency_key,
            },
            json=publish_payload,
        )
        assert resp_pub1.status_code == 202
        data_pub1 = resp_pub1.json()
        assert data_pub1["status"] == "succeeded"
        version_id = data_pub1["version_id"]
        operation_id = data_pub1["operation_id"]

        # Verify app status is now active
        resp_app = await client.get(
            f"/v1/apps/{app_id}",
            headers={"Authorization": "Bearer mock-alice-token"},
        )
        assert resp_app.json()["status"] == "active"
        assert resp_app.json()["current_version_id"] == version_id

        # 3. Idempotent Retry with same key & payload
        resp_pub_retry = await client.post(
            f"/v1/apps/{app_id}/publish",
            headers={
                "Authorization": "Bearer mock-alice-token",
                "Idempotency-Key": idempotency_key,
            },
            json=publish_payload,
        )
        assert resp_pub_retry.status_code == 202
        assert resp_pub_retry.json()["operation_id"] == operation_id
        assert resp_pub_retry.json()["version_id"] == version_id

        # 4. Same Idempotency Key with DIFFERENT payload -> Conflict (409)
        different_payload = {
            **publish_payload,
            "artifact": {"ref": "artifacts/different.tar.gz", "sha256": "1111111111111111111111111111111111111111111111111111111111111111"},
        }
        resp_pub_conflict = await client.post(
            f"/v1/apps/{app_id}/publish",
            headers={
                "Authorization": "Bearer mock-alice-token",
                "Idempotency-Key": idempotency_key,
            },
            json=different_payload,
        )
        assert resp_pub_conflict.status_code == 409
        assert resp_pub_conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"

        # 5. Optimistic Concurrency Check (expected_current_version mismatch)
        resp_concurrency_conflict = await client.post(
            f"/v1/apps/{app_id}/publish",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "manifest": manifest,
                "artifact": {"ref": artifact_ref},
                "expected_current_version": 99,  # Current is 1
            },
        )
        assert resp_concurrency_conflict.status_code == 409
        assert resp_concurrency_conflict.json()["detail"]["code"] == "VERSION_CONFLICT"

        # 6. Publish Version 2 using Multipart upload
        files = {
            "bundle": ("bundle.tar.gz", b"version 2 bundle binary data", "application/gzip"),
        }
        data = {
            "manifest": json.dumps(manifest),
            "change_description": "Version 2 via multipart",
            "expected_current_version": "1",
        }
        resp_pub2 = await client.post(
            f"/v1/apps/{app_id}/publish",
            headers={"Authorization": "Bearer mock-alice-token"},
            data=data,
            files=files,
        )
        assert resp_pub2.status_code == 202
        v2_version_id = resp_pub2.json()["version_id"]
        assert v2_version_id != version_id

        # 7. List Versions
        resp_versions = await client.get(
            f"/v1/apps/{app_id}/versions",
            headers={"Authorization": "Bearer mock-alice-token"},
        )
        assert resp_versions.status_code == 200
        items = resp_versions.json()["items"]
        assert len(items) >= 2
        assert items[0]["version_number"] == 2
        assert items[1]["version_number"] == 1

        # 8. Check Operation Status endpoint
        resp_op = await client.get(
            f"/v1/apps/{app_id}/operations/{operation_id}",
            headers={"Authorization": "Bearer mock-alice-token"},
        )
        assert resp_op.status_code == 200
        assert resp_op.json()["status"] == "succeeded"


@pytest.mark.asyncio
async def test_publish_capability_approval_required():
    transport = ASGITransport(app=app)
    app_key = f"app-{uuid.uuid4().hex[:8]}"
    manifest = {
        **VALID_MANIFEST,
        "id": app_key,
        "capabilities": {
            "connectors": [
                {
                    "name": "slack.post",
                    "identity": "service",  # Triggers approval_required
                    "required_roles": ["admin"],
                }
            ]
        },
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp_create = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": app_key,
                "name": "App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": {**VALID_MANIFEST, "id": app_key},
            },
        )
        assert resp_create.status_code == 201
        app_id = resp_create.json()["id"]

        resp_pub = await client.post(
            f"/v1/apps/{app_id}/publish",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "manifest": manifest,
                "artifact": {"ref": "artifacts/dummy.tar.gz"},
            },
        )
        assert resp_pub.status_code == 422
        assert resp_pub.json()["detail"]["code"] == "CAPABILITY_APPROVAL_REQUIRED"
