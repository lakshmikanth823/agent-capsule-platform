"""
Tests for Apps API endpoints (create, get, list, validate).
"""
import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from main import app

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
async def test_create_app_success_and_audit():
    transport = ASGITransport(app=app)
    app_key = f"app-{uuid.uuid4().hex[:8]}"
    manifest = dict(VALID_MANIFEST)
    manifest["id"] = app_key

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create app
        resp = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": app_key,
                "name": "Survey Application",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["app_key"] == app_key
        assert data["status"] == "draft"
        assert data["shape"] == "web-app"
        assert data["runtime"] == "node22"
        app_id = data["id"]

        # Get app by ID
        resp_get = await client.get(
            f"/v1/apps/{app_id}",
            headers={"Authorization": "Bearer mock-alice-token"},
        )
        assert resp_get.status_code == 200
        assert resp_get.json()["id"] == app_id

        # Get app by key
        resp_get_key = await client.get(
            f"/v1/apps/{app_key}",
            headers={"Authorization": "Bearer mock-alice-token"},
        )
        assert resp_get_key.status_code == 200
        assert resp_get_key.json()["id"] == app_id

        # List apps
        resp_list = await client.get(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
        )
        assert resp_list.status_code == 200
        items = resp_list.json()["items"]
        assert any(item["id"] == app_id for item in items)

        # Audit events check
        resp_audit = await client.get(
            f"/v1/audit/events?app_id={app_id}",
            headers={"Authorization": "Bearer mock-alice-token"},
        )
        assert resp_audit.status_code == 200
        events = resp_audit.json()
        assert any(e["action"] == "app.create" and e["target_id"] == app_id for e in events)


@pytest.mark.asyncio
async def test_create_app_id_mismatch():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": "app-outer",
                "name": "App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": {**VALID_MANIFEST, "id": "app-inner"},
            },
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "ID_MISMATCH"


@pytest.mark.asyncio
async def test_create_app_duplicate_conflict():
    transport = ASGITransport(app=app)
    app_key = f"app-{uuid.uuid4().hex[:8]}"
    manifest = {**VALID_MANIFEST, "id": app_key}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": app_key,
                "name": "App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": app_key,
                "name": "App Duplicate",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert resp2.status_code == 409
        assert resp2.json()["detail"]["code"] == "APP_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_create_app_invalid_manifest():
    transport = ASGITransport(app=app)
    app_key = f"app-{uuid.uuid4().hex[:8]}"
    invalid_manifest = {
        **VALID_MANIFEST,
        "id": app_key,
        "shape": "worker",  # Unsupported shape
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": app_key,
                "name": "App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": invalid_manifest,
            },
        )
        assert resp.status_code == 422
        data = resp.json()["detail"]
        assert data["valid"] is False
        assert any(c["code"] == "unsupported_shape" for c in data["checks"])


@pytest.mark.asyncio
async def test_validate_app_endpoint():
    transport = ASGITransport(app=app)
    app_key = f"app-{uuid.uuid4().hex[:8]}"
    manifest = {**VALID_MANIFEST, "id": app_key}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create app first
        resp_create = await client.post(
            "/v1/apps",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={
                "id": app_key,
                "name": "App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert resp_create.status_code == 201
        app_id = resp_create.json()["id"]

        # Validate with valid manifest
        resp_val = await client.post(
            f"/v1/apps/{app_id}/validate",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={"manifest": manifest},
        )
        assert resp_val.status_code == 200
        assert resp_val.json()["valid"] is True

        # Validate with invalid manifest
        resp_val_bad = await client.post(
            f"/v1/apps/{app_id}/validate",
            headers={"Authorization": "Bearer mock-alice-token"},
            json={"manifest": {**manifest, "runtime": "python312"}},
        )
        assert resp_val_bad.status_code == 200
        assert resp_val_bad.json()["valid"] is False
