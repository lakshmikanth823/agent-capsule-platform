"""
Comprehensive Test Suite for Credential Broker (Prompt 15)
Tests:
- Secret encryption (AES-256-GCM) and zero leakage in DB, responses, and logs.
- Apps cannot read secrets from environment, files, or logs.
- Undeclared connectors are rejected with 403 CAPABILITY_DENIED.
- Viewer identity enforcement (acts_as: viewer requires x-capsule-identity).
- Service identity enforcement (acts_as: service).
- Service identity refusal when organization policy forbids it (403 SERVICE_IDENTITY_FORBIDDEN).
- Connector refusal when organization policy disables it (403 CONNECTOR_DISABLED).
- Real connector test: slack.post attaches credentials at egress layer.
- Test connector test: fake.echo verifies credential attachment without leaking secret.
- Audit logging of connector invocations with masked metadata.
"""
import os
import uuid
import json
import pytest
import httpx
from httpx import AsyncClient, ASGITransport
from main import app
from db.session import db_context
from db.models import ConnectorCredential, Organization, App
from db.dal import OrganizationDAL, AppDAL, UserDAL, ConnectorCredentialDAL, AuditDAL
from crypto import encrypt_secret, decrypt_secret, mask_sensitive_data

MOCK_ALICE_TOKEN = "mock-alice-token"  # Owner of Acme Corp


@pytest.mark.asyncio
async def test_secret_encryption_and_zero_leakage():
    """
    Verifies that secrets are stored encrypted with AES-256-GCM in the database,
    cannot be read as plaintext, and are never returned in API responses.
    """
    transport = ASGITransport(app=app)
    raw_secret = {"bot_token": "xoxb-1234567890-abcdef123456", "signing_secret": "sec-987654"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Get Acme Corp org
        async with db_context() as session:
            org_dal = OrganizationDAL(session)
            org = await org_dal.get_by_slug("acme-corp")
            org_id = org.id

        # 1. Admin sets credential via API
        set_res = await client.post(
            f"/v1/organizations/{org_id}/connectors/fake.echo/credentials",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
            json={
                "identity_type": "service",
                "credential": raw_secret,
            },
        )
        assert set_res.status_code == 200, set_res.text
        resp_data = set_res.json()

        # Zero leakage: Response MUST NOT contain raw secrets or encrypted data
        assert "bot_token" not in json.dumps(resp_data)
        assert "signing_secret" not in json.dumps(resp_data)
        assert "encrypted_data" not in resp_data
        assert resp_data["connector_name"] == "fake.echo"
        assert resp_data["identity_type"] == "service"
        assert resp_data["status"] == "configured"

        # 2. Verify in database: data is encrypted ciphertext, NOT plaintext
        async with db_context() as session:
            cred_dal = ConnectorCredentialDAL(session)
            record = await cred_dal.get_credential_record(org_id, "fake.echo", "service")
            assert record is not None
            assert "xoxb-1234567890" not in record.encrypted_data
            assert "sec-987654" not in record.encrypted_data

            # Decrypt in memory: matches original secret
            decrypted = decrypt_secret(record.encrypted_data)
            assert decrypted == raw_secret

        # 3. List credentials endpoint: returns metadata only, NO secrets
        list_res = await client.get(
            f"/v1/organizations/{org_id}/connectors",
            headers={"Authorization": f"Bearer {MOCK_ALICE_TOKEN}"},
        )
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert "bot_token" not in json.dumps(list_data)
        assert any(c["connector_name"] == "fake.echo" for c in list_data["connectors"])


@pytest.mark.asyncio
async def test_app_cannot_read_secrets_from_env_or_logs():
    """
    Verifies that connector credentials are not in environment variables or logs.
    """
    # 1. Environment variables check
    assert "SLACK_BOT_TOKEN" not in os.environ
    assert "SLACK_WEBHOOK_URL" not in os.environ
    assert "CONNECTOR_SECRET" not in os.environ

    # 2. Mask sensitive data check
    payload_with_secrets = {
        "channel": "#general",
        "bot_token": "super-secret-token",
        "api_key": "secret-key-xyz",
        "nested": {"client_secret": "my-secret", "safe_field": "public_value"},
    }
    masked = mask_sensitive_data(payload_with_secrets)
    assert masked["bot_token"] == "[REDACTED]"
    assert masked["api_key"] == "[REDACTED]"
    assert masked["nested"]["client_secret"] == "[REDACTED]"
    assert masked["nested"]["safe_field"] == "public_value"


@pytest.mark.asyncio
async def test_undeclared_connector_denied():
    """
    Verifies that an app cannot invoke a connector not declared in its manifest (403 CAPABILITY_DENIED).
    """
    transport = ASGITransport(app=app)
    app_key = f"app-undeclared-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        # Create app with NO connectors declared
        await app_dal.create(
            app_key=app_key,
            name="Undeclared Test App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Undeclared Test App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "db": {"type": "sqlite"},
                    "connectors": [],  # Empty connectors!
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        invoke_res = await client.post(
            "/v1/connectors/fake.echo/invoke",
            headers={"x-capsule-key": app_key},
            json={"message": "test"},
        )
        assert invoke_res.status_code == 403, invoke_res.text
        data = invoke_res.json()["detail"]
        assert data["code"] == "CAPABILITY_DENIED"
        assert "not declared connector capability" in data["message"]


@pytest.mark.asyncio
async def test_viewer_identity_enforcement():
    """
    Verifies that a connector with acts_as: 'viewer' requires a signed viewer identity.
    Fails with 401 VIEWER_IDENTITY_REQUIRED when missing.
    Succeeds and uses viewer context when provided.
    """
    transport = ASGITransport(app=app)
    app_key = f"app-viewer-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        # Set viewer credential for fake.echo
        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="fake.echo",
            identity_type="viewer",
            credential_data={"viewer_api_key": "viewer-secret-123"},
        )

        # Create app with acts_as: viewer
        await app_dal.create(
            app_key=app_key,
            name="Viewer Connector App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Viewer Connector App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "connectors": [
                        {"name": "fake.echo", "acts_as": "viewer"}
                    ],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Invocation WITHOUT x-capsule-identity header -> 401 Unauthorized
        res_no_identity = await client.post(
            "/v1/connectors/fake.echo/invoke",
            headers={"x-capsule-key": app_key},
            json={"message": "hello without identity"},
        )
        assert res_no_identity.status_code == 401, res_no_identity.text
        detail = res_no_identity.json()["detail"]
        assert detail["code"] == "VIEWER_IDENTITY_REQUIRED"

        # 2. Invocation WITH x-capsule-identity header -> 200 OK
        viewer_identity = {
            "sub": str(alice.id),
            "email": "alice@example.com",
            "roles": ["employee", "manager"],
        }
        res_with_identity = await client.post(
            "/v1/connectors/fake.echo/invoke",
            headers={
                "x-capsule-key": app_key,
                "x-capsule-identity": json.dumps(viewer_identity),
            },
            json={"message": "hello with identity"},
        )
        assert res_with_identity.status_code == 200, res_with_identity.text
        data = res_with_identity.json()
        assert data["connector"] == "fake.echo"
        assert data["credential_attached"] is True
        assert data["identity"]["email"] == "alice@example.com"
        assert data["echo"]["message"] == "hello with identity"


@pytest.mark.asyncio
async def test_service_identity_policy_control():
    """
    Verifies service identity:
    - Allowed when org policy permits it.
    - Blocked with 403 SERVICE_IDENTITY_FORBIDDEN when org policy prohibits it.
    """
    transport = ASGITransport(app=app)
    app_key = f"app-service-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        # Set service credential for fake.echo
        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="fake.echo",
            identity_type="service",
            credential_data={"service_token": "svc-secret-token"},
        )

        # Create app with acts_as: service
        await app_dal.create(
            app_key=app_key,
            name="Service Connector App",
            organization_id=org.id,
            owner_user_id=alice.id,
            manifest={
                "apiVersion": "capsule/v1alpha1",
                "id": app_key,
                "name": "Service Connector App",
                "shape": "web-app",
                "runtime": "node22",
                "capabilities": {
                    "connectors": [
                        {"name": "fake.echo", "acts_as": "service"}
                    ],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. When policy allows service identity -> Succeeds
        res_allowed = await client.post(
            "/v1/connectors/fake.echo/invoke",
            headers={"x-capsule-key": app_key},
            json={"query": "run-service-batch"},
        )
        assert res_allowed.status_code == 200, res_allowed.text
        assert res_allowed.json()["credential_attached"] is True

        # 2. Update org policy to block service identity: allow_service_identity = False
        async with db_context() as session:
            org_dal = OrganizationDAL(session)
            org = await org_dal.get_by_slug("acme-corp")
            org.environment_profile = {**org.environment_profile, "allow_service_identity": False}
            await session.commit()

        # 3. Invocation MUST be refused
        res_blocked = await client.post(
            "/v1/connectors/fake.echo/invoke",
            headers={"x-capsule-key": app_key},
            json={"query": "run-service-batch"},
        )
        assert res_blocked.status_code == 403, res_blocked.text
        detail = res_blocked.json()["detail"]
        assert detail["code"] == "SERVICE_IDENTITY_FORBIDDEN"
        assert "Organization policy prohibits service identity" in detail["message"]

        # Restore org policy
        async with db_context() as session:
            org_dal = OrganizationDAL(session)
            org = await org_dal.get_by_slug("acme-corp")
            org.environment_profile = {**org.environment_profile, "allow_service_identity": True}
            await session.commit()


@pytest.mark.asyncio
async def test_connector_disabled_by_org_policy():
    """
    Verifies that if an organization policy disables a connector, it is refused with 403 CONNECTOR_DISABLED.
    """
    transport = ASGITransport(app=app)
    app_key = f"app-disabled-{uuid.uuid4().hex[:8]}"

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        cred_dal = ConnectorCredentialDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        # Disable fake.echo in org environment profile
        org.environment_profile = {
            **org.environment_profile,
            "disabled_connectors": ["fake.echo"],
        }
        await session.commit()

        await cred_dal.set_credential(
            organization_id=org.id,
            connector_name="fake.echo",
            identity_type="service",
            credential_data={"token": "test"},
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
                    "connectors": [{"name": "fake.echo", "acts_as": "service"}],
                },
            },
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/connectors/fake.echo/invoke",
            headers={"x-capsule-key": app_key},
            json={"msg": "ping"},
        )
        assert res.status_code == 403, res.text
        detail = res.json()["detail"]
        assert detail["code"] == "CONNECTOR_DISABLED"

        # Restore org policy
        async with db_context() as session:
            org_dal = OrganizationDAL(session)
            org = await org_dal.get_by_slug("acme-corp")
            profile = dict(org.environment_profile)
            profile.pop("disabled_connectors", None)
            org.environment_profile = profile
            await session.commit()


@pytest.mark.asyncio
async def test_slack_post_connector_credential_attachment():
    """
    Verifies real connector slack.post:
    - Attaches credentials at the egress layer.
    - Posts message to Slack endpoint.
    - App receives success response without raw token leakage.
    """
    import http.server
    import threading

    received_slack_requests = []

    class MockSlackHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            received_slack_requests.append({
                "path": self.path,
                "headers": dict(self.headers),
                "body": json.loads(body) if body else {},
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "channel": "#hr-leave",
                "ts": "1726918800.000100",
                "message": {"text": "Alice leave request"},
            }).encode("utf-8"))

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), MockSlackHandler)
    server_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    os.environ["SLACK_API_URL"] = f"http://127.0.0.1:{server_port}/api/chat.postMessage"

    transport = ASGITransport(app=app)
    app_key = f"app-slack-{uuid.uuid4().hex[:8]}"

    try:
        async with db_context() as session:
            org_dal = OrganizationDAL(session)
            user_dal = UserDAL(session)
            app_dal = AppDAL(session)
            cred_dal = ConnectorCredentialDAL(session)

            org = await org_dal.get_by_slug("acme-corp")
            alice = await user_dal.get_by_email("alice@example.com")

            # Store encrypted Slack credential
            await cred_dal.set_credential(
                organization_id=org.id,
                connector_name="slack.post",
                identity_type="service",
                credential_data={"bot_token": "xoxb-real-slack-token-555"},
            )

            # Create app with slack.post declared
            await app_dal.create(
                app_key=app_key,
                name="Slack Post App",
                organization_id=org.id,
                owner_user_id=alice.id,
                manifest={
                    "apiVersion": "capsule/v1alpha1",
                    "id": app_key,
                    "name": "Slack Post App",
                    "shape": "web-app",
                    "runtime": "node22",
                    "capabilities": {
                        "connectors": [
                            {"name": "slack.post", "channel": "#hr-leave", "acts_as": "service"}
                        ],
                    },
                },
            )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            invoke_res = await client.post(
                "/v1/connectors/slack.post/invoke",
                headers={"x-capsule-key": app_key},
                json={"text": "Alice submitted leave request for July 1-5"},
            )
            assert invoke_res.status_code == 200, invoke_res.text
            resp_data = invoke_res.json()

            # Verify response to the app
            assert resp_data["connector"] == "slack.post"
            assert resp_data["status"] == "success"
            assert resp_data["ok"] is True
            assert resp_data["channel"] == "#hr-leave"
            # Zero leakage check
            assert "xoxb-real-slack-token-555" not in json.dumps(resp_data)

            # Verify mock Slack server received the attached token
            assert len(received_slack_requests) == 1
            slack_req = received_slack_requests[0]
            auth_header = slack_req["headers"].get("authorization") or slack_req["headers"].get("Authorization")
            assert auth_header == "Bearer xoxb-real-slack-token-555"
            assert slack_req["body"]["channel"] == "#hr-leave"
            assert slack_req["body"]["text"] == "Alice submitted leave request for July 1-5"

    finally:
        server.shutdown()
        os.environ.pop("SLACK_API_URL", None)


@pytest.mark.asyncio
async def test_audit_logging_no_secrets():
    """
    Verifies that connector invocations produce audit events and that no secrets are logged.
    """
    async with db_context() as session:
        audit_dal = AuditDAL(session)
        events = await audit_dal.list_events(limit=20)
        connector_events = [e for e in events if e.action == "connector.invoke"]
        assert len(connector_events) > 0

        for event in connector_events:
            event_meta_str = json.dumps(event.metadata_)
            assert "xoxb-" not in event_meta_str
            assert "viewer-secret" not in event_meta_str
            assert "svc-secret" not in event_meta_str
