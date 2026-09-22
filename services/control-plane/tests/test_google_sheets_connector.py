"""
Comprehensive Test Suite for Google Sheets Connector (Prompt 25)
Requirements:
1. Fake Google server: handles spreadsheet value reads & OAuth refresh.
2. Viewer with access gets data.
3. Viewer without access gets permission error (403 PERMISSION_DENIED).
4. App never sees token (zero token leakage in response payload and audit logs).
5. App cannot request sheet outside allowed list (403 SPREADSHEET_NOT_ALLOWED).
6. Revocation stops access immediately (disconnect / revoked token).
7. Two users with different sheet permissions see different results from the same app.
8. Admin switch in Environment Profile to allow or forbid this connector (403 CONNECTOR_DISABLED).
9. Auto-refresh on expired token.
10. Consent flow and user deprovisioning.
"""
import os
import time
import uuid
import json
import pytest
import httpx
from httpx import AsyncClient, ASGITransport
from main import app
from db.session import db_context
from db.models import ConnectorCredential, Organization, App, AuditEvent
from db.dal import OrganizationDAL, AppDAL, UserDAL, ConnectorCredentialDAL, AuditDAL
from crypto import encrypt_secret, decrypt_secret

MOCK_ALICE_TOKEN = "mock-alice-token"


class FakeGoogleTransport(httpx.AsyncBaseTransport):
    """
    Hermetic fake Google server simulating Google Sheets API v4 and OAuth2 token endpoint.
    """
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        auth = request.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else auth.strip()

        # 1. OAuth2 Token Refresh Endpoint
        if "oauth2.googleapis.com" in url or "token" in url:
            body = request.content.decode("utf-8")
            if "refresh_token=valid-refresh-token" in body or "refresh_token=alice-refresh" in body:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "refreshed-access-token",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                    },
                )
            elif "refresh_token=revoked-refresh" in body:
                return httpx.Response(
                    400,
                    json={"error": "invalid_grant", "error_description": "Token has been revoked."},
                )
            return httpx.Response(
                200,
                json={
                    "access_token": "refreshed-auto-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )

        # 2. Google Sheets API Endpoint: /v4/spreadsheets/{id}/values/{range}
        if not token or token in ("revoked-token", "invalid-token"):
            return httpx.Response(
                401,
                json={"error": {"code": 401, "message": "Request is missing valid authentication credential."}},
            )

        # Extract spreadsheet ID and range from URL
        # e.g. https://sheets.googleapis.com/v4/spreadsheets/sheet-123/values/A1:Z100
        parts = url.split("/spreadsheets/")[1].split("/values/")
        sheet_id = parts[0]
        sheet_range = parts[1] if len(parts) > 1 else "A1:Z100"

        # Permission matrix:
        # alice-token: access to "sheet-all" and "sheet-alice-only"
        # bob-token: access to "sheet-all" and "sheet-bob-only"
        # no-access-token: no sheets accessible
        # refreshed-access-token: access to "sheet-all"
        if token == "alice-token":
            if sheet_id == "sheet-alice-only":
                return httpx.Response(
                    200,
                    json={
                        "range": sheet_range,
                        "majorDimension": "ROWS",
                        "values": [["ID", "Owner"], ["ALICE-01", "Alice Smith"]],
                    },
                )
            elif sheet_id == "sheet-all":
                return httpx.Response(
                    200,
                    json={
                        "range": sheet_range,
                        "majorDimension": "ROWS",
                        "values": [["Title", "Status"], ["Quarterly Plan", "Active"]],
                    },
                )
            else:
                return httpx.Response(
                    403,
                    json={"error": {"code": 403, "message": "The caller does not have permission"}},
                )

        if token == "bob-token":
            if sheet_id == "sheet-bob-only":
                return httpx.Response(
                    200,
                    json={
                        "range": sheet_range,
                        "majorDimension": "ROWS",
                        "values": [["ID", "Owner"], ["BOB-01", "Bob Jones"]],
                    },
                )
            elif sheet_id == "sheet-all":
                return httpx.Response(
                    200,
                    json={
                        "range": sheet_range,
                        "majorDimension": "ROWS",
                        "values": [["Title", "Status"], ["Quarterly Plan", "Active"]],
                    },
                )
            else:
                return httpx.Response(
                    403,
                    json={"error": {"code": 403, "message": "The caller does not have permission"}},
                )

        if token == "refreshed-access-token":
            return httpx.Response(
                200,
                json={
                    "range": sheet_range,
                    "majorDimension": "ROWS",
                    "values": [["Status", "Refreshed"], ["Data", "Success"]],
                },
            )

        if token == "no-access-token":
            return httpx.Response(
                403,
                json={"error": {"code": 403, "message": "The caller does not have permission"}},
            )

        if sheet_id == "not-found-sheet":
            return httpx.Response(
                404,
                json={"error": {"code": 404, "message": "Requested entity was not found."}},
            )

        return httpx.Response(
            200,
            json={
                "range": sheet_range,
                "majorDimension": "ROWS",
                "values": [["DefaultRow1", "DefaultRow2"]],
            },
        )


@pytest.fixture(autouse=True)
def patch_google_httpx(monkeypatch):
    """
    Patches httpx.AsyncClient so that outbound requests without a custom transport
    are routed to FakeGoogleTransport, while ASGI test client calls remain unaffected.
    """
    fake_transport = FakeGoogleTransport()
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        if "transport" not in kwargs or kwargs.get("transport") is None:
            kwargs["transport"] = fake_transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


@pytest.mark.asyncio
async def test_viewer_with_access_gets_data():
    """
    Requirement: Viewer with access gets sheet data values.
    App receives only data, never credentials.
    """
    transport = ASGITransport(app=app)
    app_key = f"sheets-app-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        # Save Alice's viewer credential
        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="sheets.read",
            identity_type="viewer",
            credential_data={
                "access_token": "alice-token",
                "refresh_token": "alice-refresh",
                "expires_at": time.time() + 3600,
            },
            user_id=alice.id,
        )

        # Create app declaring sheets.read as viewer
        await app_dal.create(
            app_key=app_key,
            name="Sheets Read App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Sheets Read App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "connectors": [
                        {
                            "name": "sheets.read",
                            "acts_as": "viewer",
                            "spreadsheet_ids": ["sheet-all", "sheet-alice-only"],
                        }
                    ],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        viewer_identity = {
            "sub": str(alice.id),
            "email": "alice@example.com",
            "org_id": str(org.id),
        }

        res = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps(viewer_identity),
            },
            json={
                "spreadsheet_id": "sheet-all",
                "range": "A1:B10",
            },
        )

        assert res.status_code == 200, res.text
        data = res.json()
        assert data["connector"] == "sheets.read"
        assert data["status"] == "success"
        assert data["spreadsheet_id"] == "sheet-all"
        assert data["values"] == [["Title", "Status"], ["Quarterly Plan", "Active"]]

        # ZERO token leakage verification: App response MUST NOT contain any token
        serialized = json.dumps(data)
        assert "alice-token" not in serialized
        assert "alice-refresh" not in serialized
        assert "Bearer" not in serialized
        assert "access_token" not in serialized


@pytest.mark.asyncio
async def test_two_users_with_different_permissions_see_different_results():
    """
    Requirement: Two users with different sheet permissions must see different results from the same app.
    Alice sees AliceData; Bob sees BobData. Bob cannot access Alice's sheet.
    """
    transport = ASGITransport(app=app)
    app_key = f"sheets-multiuser-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")
        bob = await user_dal.get_by_email("bob@example.com")
        if not bob:
            bob = await user_dal.create(
                email="bob@example.com",
                display_name="Bob Colleague",
                identity_subject="google-oauth2|bob-67890",
                identity_issuer="https://accounts.google.com",
                status="active",
            )
            await user_dal.add_to_org(org.id, bob.id, platform_role="user")

        # Set Alice's token
        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="sheets.read",
            identity_type="viewer",
            credential_data={"access_token": "alice-token", "expires_at": time.time() + 3600},
            user_id=alice.id,
        )

        # Set Bob's token
        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="sheets.read",
            identity_type="viewer",
            credential_data={"access_token": "bob-token", "expires_at": time.time() + 3600},
            user_id=bob.id,
        )

        # Single app declaring both sheets
        await app_dal.create(
            app_key=app_key,
            name="Multiuser Sheets App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Multiuser Sheets App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "connectors": [
                        {
                            "name": "sheets.read",
                            "acts_as": "viewer",
                            "spreadsheet_ids": ["sheet-alice-only", "sheet-bob-only", "sheet-all"],
                        }
                    ],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Alice reads Alice sheet -> succeeds
        alice_res = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps({"sub": str(alice.id), "email": "alice@example.com", "org_id": str(org.id)}),
            },
            json={"spreadsheet_id": "sheet-alice-only"},
        )
        assert alice_res.status_code == 200
        assert alice_res.json()["values"][1][1] == "Alice Smith"

        # 2. Bob reads Bob sheet -> succeeds with Bob's data
        bob_res = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps({"sub": str(bob.id), "email": "bob@example.com", "org_id": str(org.id)}),
            },
            json={"spreadsheet_id": "sheet-bob-only"},
        )
        assert bob_res.status_code == 200
        assert bob_res.json()["values"][1][1] == "Bob Jones"

        # 3. Bob reads Alice sheet -> blocked with 403 PERMISSION_DENIED
        bob_forbidden = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps({"sub": str(bob.id), "email": "bob@example.com", "org_id": str(org.id)}),
            },
            json={"spreadsheet_id": "sheet-alice-only"},
        )
        assert bob_forbidden.status_code == 403
        assert bob_forbidden.json()["detail"]["code"] == "PERMISSION_DENIED"

        # 4. Alice reads Bob sheet -> blocked with 403 PERMISSION_DENIED
        alice_forbidden = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps({"sub": str(alice.id), "email": "alice@example.com", "org_id": str(org.id)}),
            },
            json={"spreadsheet_id": "sheet-bob-only"},
        )
        assert alice_forbidden.status_code == 403
        assert alice_forbidden.json()["detail"]["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_app_cannot_request_sheet_outside_allowed_list():
    """
    Requirement: Manifest restricts access to a list of spreadsheet ids.
    Requesting a sheet not in the manifest must be blocked with 403 SPREADSHEET_NOT_ALLOWED.
    """
    transport = ASGITransport(app=app)
    app_key = f"sheets-restricted-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="sheets.read",
            identity_type="viewer",
            credential_data={"access_token": "alice-token", "expires_at": time.time() + 3600},
            user_id=alice.id,
        )

        await app_dal.create(
            app_key=app_key,
            name="Restricted Sheets App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Restricted Sheets App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "connectors": [
                        {
                            "name": "sheets.read",
                            "acts_as": "viewer",
                            "spreadsheet_ids": ["sheet-allowed-1", "sheet-allowed-2"],
                        }
                    ],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request unallowed sheet
        res = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps({"sub": str(alice.id), "org_id": str(org.id)}),
            },
            json={"spreadsheet_id": "sheet-unauthorized-target"},
        )
        assert res.status_code == 403
        detail = res.json()["detail"]
        assert detail["code"] == "SPREADSHEET_NOT_ALLOWED"
        assert "not permitted by the application manifest" in detail["message"]
        assert "allowed_spreadsheets" in detail


@pytest.mark.asyncio
async def test_revocation_and_disconnect_stops_access_immediately():
    """
    Requirement: When a user disconnects or token is revoked, access stops immediately.
    """
    transport = ASGITransport(app=app)
    app_key = f"sheets-revoke-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="sheets.read",
            identity_type="viewer",
            credential_data={"access_token": "alice-token", "expires_at": time.time() + 3600},
            user_id=alice.id,
        )

        await app_dal.create(
            app_key=app_key,
            name="Revoke Test App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Revoke Test App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "connectors": [{"name": "sheets.read", "acts_as": "viewer"}],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initial call succeeds
        res1 = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps({"sub": str(alice.id), "org_id": str(org.id)}),
            },
            json={"spreadsheet_id": "sheet-all"},
        )
        assert res1.status_code == 200

        # User disconnects connector
        disc_res = await client.post(
            "/v1/connectors/sheets.read/disconnect",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"user_id": str(alice.id), "organization_id": str(org.id)},
        )
        assert disc_res.status_code == 200
        assert disc_res.json()["status"] == "disconnected"

        # Subsequent invoke fails immediately: credentials no longer configured
        res2 = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps({"sub": str(alice.id), "org_id": str(org.id)}),
            },
            json={"spreadsheet_id": "sheet-all"},
        )
        assert res2.status_code == 404
        assert res2.json()["detail"]["code"] == "CREDENTIAL_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_google_token_revocation_detection():
    """
    Requirement: If Google returns 401 Unauthorized (token revoked), broker returns 401 OAUTH_TOKEN_REVOKED.
    """
    transport = ASGITransport(app=app)
    app_key = f"sheets-revoked-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        # Save already-revoked token
        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="sheets.read",
            identity_type="viewer",
            credential_data={"access_token": "revoked-token", "expires_at": time.time() + 3600},
            user_id=alice.id,
        )

        await app_dal.create(
            app_key=app_key,
            name="Revoked Google Token App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Revoked Google Token App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "connectors": [{"name": "sheets.read", "acts_as": "viewer"}],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps({"sub": str(alice.id), "org_id": str(org.id)}),
            },
            json={"spreadsheet_id": "sheet-all"},
        )
        assert res.status_code == 401
        assert res.json()["detail"]["code"] == "OAUTH_TOKEN_REVOKED"


@pytest.mark.asyncio
async def test_admin_switch_in_environment_profile_forbids_connector():
    """
    Requirement: Admin switch in Environment Profile to allow or forbid this connector.
    """
    transport = ASGITransport(app=app)
    app_key = f"sheets-disabled-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        # Set environment profile with sheets.read disabled
        profile = org.environment_profile or {}
        profile["disabled_connectors"] = ["sheets.read"]
        await org_dal.update_environment_profile(org.id, profile)

        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="sheets.read",
            identity_type="viewer",
            credential_data={"access_token": "alice-token"},
            user_id=alice.id,
        )

        await app_dal.create(
            app_key=app_key,
            name="Disabled Connector App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Disabled Connector App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "connectors": [{"name": "sheets.read", "acts_as": "viewer"}],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps({"sub": str(alice.id), "org_id": str(org.id)}),
            },
            json={"spreadsheet_id": "sheet-all"},
        )
        assert res.status_code == 403
        assert res.json()["detail"]["code"] == "CONNECTOR_DISABLED"

    # Reset profile disabled_connectors
    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        profile["disabled_connectors"] = []
        await org_dal.update_environment_profile(org.id, profile)


@pytest.mark.asyncio
async def test_acts_as_service_is_strictly_rejected():
    """
    Requirement: sheets.read proves viewer identity and forbids service identity.
    """
    transport = ASGITransport(app=app)
    app_key = f"sheets-service-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        # Manifest attempts acts_as: service
        await app_dal.create(
            app_key=app_key,
            name="Service Sheets App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Service Sheets App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "connectors": [{"name": "sheets.read", "acts_as": "service"}],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={"x-capsule-key": app_key},
            json={"spreadsheet_id": "sheet-all"},
        )
        assert res.status_code == 403
        assert res.json()["detail"]["code"] == "SERVICE_IDENTITY_FORBIDDEN"


@pytest.mark.asyncio
async def test_token_auto_refresh_on_expired_token():
    """
    Requirement: Handle refresh. When access_token is expired, broker calls token endpoint
    using refresh_token, updates stored token, and completes request successfully.
    """
    transport = ASGITransport(app=app)
    app_key = f"sheets-refresh-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        # Expired access token with valid refresh token
        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="sheets.read",
            identity_type="viewer",
            credential_data={
                "access_token": "expired-access-token",
                "refresh_token": "valid-refresh-token",
                "expires_at": time.time() - 3600,  # expired 1 hour ago
            },
            user_id=alice.id,
        )

        await app_dal.create(
            app_key=app_key,
            name="Token Refresh App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Token Refresh App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "connectors": [{"name": "sheets.read", "acts_as": "viewer"}],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/connectors/sheets.read/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps({"sub": str(alice.id), "org_id": str(org.id)}),
            },
            json={"spreadsheet_id": "sheet-all"},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["status"] == "success"

        # Verify in DB that refreshed token was persisted
        async with db_context() as session:
            cred_dal = ConnectorCredentialDAL(session)
            updated_cred = await cred_dal.get_credential(org.id, "sheets.read", "viewer", alice.id)
            assert updated_cred is not None
            assert updated_cred["access_token"] == "refreshed-access-token"
            assert updated_cred["expires_at"] > time.time()


@pytest.mark.asyncio
async def test_consent_flow_endpoints():
    """
    Requirement: Consent endpoints to inspect and save viewer OAuth tokens.
    """
    transport = ASGITransport(app=app)

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        # Ensure no credential initially
        await cred_dal.delete_credential(org.id, "sheets.read", "viewer", alice.id)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Check consent status: initially false
        status_res = await client.get(
            f"/v1/connectors/sheets.read/consent?user_id={alice.id}&organization_id={org.id}",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert status_res.status_code == 200
        assert status_res.json()["consented"] is False
        assert "https://www.googleapis.com/auth/spreadsheets.readonly" in status_res.json()["required_scopes"]

        # 2. Save consent (OAuth callback result)
        grant_res = await client.post(
            "/v1/connectors/sheets.read/consent",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "access_token": "alice-consent-token",
                "refresh_token": "alice-consent-refresh",
                "expires_in": 3600,
                "user_id": str(alice.id),
                "organization_id": str(org.id),
            },
        )
        assert grant_res.status_code == 200
        assert grant_res.json()["status"] == "consented"

        # 3. Check consent status again: now true
        status_res2 = await client.get(
            f"/v1/connectors/sheets.read/consent?user_id={alice.id}&organization_id={org.id}",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert status_res2.status_code == 200
        assert status_res2.json()["consented"] is True

        # 4. Disconnect
        disc_res = await client.post(
            "/v1/connectors/sheets.read/disconnect",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={"user_id": str(alice.id), "organization_id": str(org.id)},
        )
        assert disc_res.status_code == 200
        assert disc_res.json()["status"] == "disconnected"

        # 5. Check consent status: false again
        status_res3 = await client.get(
            f"/v1/connectors/sheets.read/consent?user_id={alice.id}&organization_id={org.id}",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert status_res3.status_code == 200
        assert status_res3.json()["consented"] is False


@pytest.mark.asyncio
async def test_deprovision_user_deletes_all_tokens():
    """
    Requirement: When a user is deprovisioned, delete their tokens.
    """
    transport = ASGITransport(app=app)

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        bob = await user_dal.get_by_email("bob@example.com")
        if not bob:
            bob = await user_dal.create(
                email="bob@example.com",
                display_name="Bob Colleague",
                identity_subject="google-oauth2|bob-67890",
                identity_issuer="https://accounts.google.com",
                status="active",
            )
            await user_dal.add_to_org(org.id, bob.id, platform_role="user")

        # Save multiple credentials for Bob
        await cred_dal.set_credential(org.id, "sheets.read", "viewer", {"access_token": "bob-t1"}, bob.id)
        await cred_dal.set_credential(org.id, "fake.echo", "viewer", {"access_token": "bob-t2"}, bob.id)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Admin deprovisions Bob's tokens
        deprov_res = await client.delete(
            f"/v1/organizations/{org.id}/users/{bob.id}/connector-tokens",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert deprov_res.status_code == 200
        assert deprov_res.json()["status"] == "deprovisioned"
        assert deprov_res.json()["deleted_count"] >= 2

        # Verify DB is clean for Bob
        async with db_context() as session:
            cred_dal = ConnectorCredentialDAL(session)
            c1 = await cred_dal.get_credential(org.id, "sheets.read", "viewer", bob.id)
            c2 = await cred_dal.get_credential(org.id, "fake.echo", "viewer", bob.id)
            assert c1 is None
            assert c2 is None
