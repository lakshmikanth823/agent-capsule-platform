"""
Tests for Quota Enforcement (Prompt 23) in the Control Plane.

Tests fail-closed structured errors:
- Apps per user quota
- SQLite database size quota
- Blob storage quota
- Request timeout quota
- AI monthly spend budget quota
"""
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import HTTPException

from main import app as fastapi_app
from services.quota_service import (
    enforce_apps_per_user_quota,
    enforce_manifest_quotas,
    get_effective_quotas,
)

MOCK_ALICE_TOKEN = "mock-alice-token"


@pytest.mark.asyncio
async def test_sqlite_size_quota_exceeded():
    transport = ASGITransport(app=fastapi_app)
    app_key = f"quota-db-{uuid.uuid4().hex[:8]}"

    # Default quota is 50MB; app requests 100MB
    manifest = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": "Excessive DB App",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["employee"],
        "capabilities": {
            "db": {"type": "sqlite"}
        },
        "limits": {
            "db_max_mb": 100
        },
        "egress": [],
    }


    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Excessive DB App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert res.status_code == 403, res.text
        detail = res.json()["detail"]
        assert detail["code"] == "QUOTA_EXCEEDED"
        assert detail["metric"] == "sqlite_max_mb"
        assert detail["limit"] == 50
        assert detail["requested"] == 100


@pytest.mark.asyncio
async def test_blob_storage_quota_exceeded():
    transport = ASGITransport(app=fastapi_app)
    app_key = f"quota-blob-{uuid.uuid4().hex[:8]}"

    # Default quota is 200MB; app requests 500MB
    manifest = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": "Excessive Blob App",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["employee"],
        "capabilities": {
            "files": {"max_mb": 500}
        },
        "egress": [],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Excessive Blob App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert res.status_code == 403, res.text
        detail = res.json()["detail"]
        assert detail["code"] == "QUOTA_EXCEEDED"
        assert detail["metric"] == "blob_storage_max_mb"
        assert detail["limit"] == 200
        assert detail["requested"] == 500


@pytest.mark.asyncio
async def test_request_timeout_quota_exceeded():
    transport = ASGITransport(app=fastapi_app)
    app_key = f"quota-timeout-{uuid.uuid4().hex[:8]}"

    # Default quota is 30s; app requests 60s
    manifest = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": "Excessive Timeout App",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["employee"],
        "capabilities": {},
        "limits": {"request_timeout_s": 60},
        "egress": [],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Excessive Timeout App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert res.status_code == 403, res.text
        detail = res.json()["detail"]
        assert detail["code"] == "QUOTA_EXCEEDED"
        assert detail["metric"] == "request_timeout_s"
        assert detail["limit"] == 30
        assert detail["requested"] == 60


@pytest.mark.asyncio
async def test_ai_budget_quota_exceeded():
    transport = ASGITransport(app=fastapi_app)
    app_key = f"quota-ai-{uuid.uuid4().hex[:8]}"

    # Default quota is $10.0; app requests $50.0
    manifest = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": "Excessive AI App",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["employee"],
        "capabilities": {
            "ai": {"monthly_budget_usd": 50.0}
        },
        "egress": [],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/apps",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "id": app_key,
                "name": "Excessive AI App",
                "shape": "web-app",
                "runtime": "node22",
                "manifest": manifest,
            },
        )
        assert res.status_code == 403, res.text
        detail = res.json()["detail"]
        assert detail["code"] == "QUOTA_EXCEEDED"
        assert detail["metric"] == "ai_monthly_budget_usd"
        assert detail["limit"] == 10.0
        assert detail["requested"] == 50.0


def test_apps_per_user_quota_unit():
    # 9 apps: allowed under default 10
    enforce_apps_per_user_quota(9)

    # 10 apps: fails closed
    with pytest.raises(HTTPException) as exc_info:
        enforce_apps_per_user_quota(10)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "QUOTA_EXCEEDED"
    assert exc_info.value.detail["metric"] == "apps_per_user"
    assert exc_info.value.detail["limit"] == 10
    assert exc_info.value.detail["current_usage"] == 10

    # Custom quota profile: 5 apps
    env_profile = {"quotas": {"apps_per_user": 5}}
    enforce_apps_per_user_quota(4, env_profile)
    with pytest.raises(HTTPException) as exc_info2:
        enforce_apps_per_user_quota(5, env_profile)
    assert exc_info2.value.detail["limit"] == 5
