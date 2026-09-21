"""
Tests for OIDC authentication and scoped publish tokens.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from auth.tokens import PublishTokenService
import uuid

@pytest.mark.asyncio
async def test_auth_missing_header():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/apps")
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_auth_invalid_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/apps", headers={"Authorization": "Bearer invalid-garbage-token"})
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_auth_expired_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/apps", headers={"Authorization": "Bearer mock-expired-token"})
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.asyncio
async def test_auth_mock_alice_and_bob_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Alice (Owner)
        resp_alice = await client.get("/v1/apps", headers={"Authorization": "Bearer mock-alice-token"})
        assert resp_alice.status_code == 200
        assert "items" in resp_alice.json()

        # Bob (Colleague)
        resp_bob = await client.get("/v1/apps", headers={"Authorization": "Bearer mock-bob-token"})
        assert resp_bob.status_code == 200
        assert "items" in resp_bob.json()


@pytest.mark.asyncio
async def test_scoped_publish_token_issuance_and_expiry():
    service = PublishTokenService(secret="test-secret")
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    app_id = uuid.uuid4()

    # 1. User-scoped token
    token_user = service.create_publish_token(user_id, org_id)
    assert token_user["scope"] == "publish:user"
    assert token_user["app_id"] is None
    payload_user = service.verify_publish_token(token_user["token"])
    assert payload_user["sub"] == str(user_id)
    assert payload_user["org_id"] == str(org_id)

    # 2. App-scoped token
    token_app = service.create_publish_token(user_id, org_id, app_id=app_id)
    assert token_app["scope"] == "publish:app"
    assert token_app["app_id"] == str(app_id)
    payload_app = service.verify_publish_token(token_app["token"])
    assert payload_app["app_id"] == str(app_id)

    # 3. Expired token
    token_expired = service.create_publish_token(user_id, org_id, expires_in_seconds=-10)
    with pytest.raises(Exception) as excinfo:
        service.verify_publish_token(token_expired["token"])
    assert "expired" in str(excinfo.value).lower()
