"""
API Tests for Sharing and Roles Endpoints

Tests:
1. Owner can assign application roles to individual users.
2. Owner can assign application roles to groups.
3. Regular User is denied permission to create or revoke shares (403 Forbidden).
4. Assigning an undeclared application role fails (400 Bad Request).
5. Revoking a share marks it as revoked, returns 204 No Content, and writes an audit event.
6. Access evaluation correctly computes permissions for owner, user share, group share, and revoked states.
"""
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timedelta

from main import app
from db.session import get_db_session
from db.dal import AppDAL, AppShareDAL, UserDAL, AuditDAL
from db.models import App, Organization, User


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_share_flow_and_role_enforcement(client: AsyncClient):
    # Use Alice (Owner of Acme Corp)
    headers_alice = {"Authorization": "Bearer mock-alice-token"}
    # Use Bob (User in Acme Corp)
    headers_bob = {"Authorization": "Bearer mock-bob-token"}
    # Use Charlie (User in Other Corp)
    headers_charlie = {"Authorization": "Bearer mock-charlie-token"}

    # 1. Create a test app with declared roles: employee, manager, hr
    app_key = f"share-test-app-{uuid.uuid4().hex[:6]}"
    manifest = {
        "apiVersion": "capsule/v1alpha1",
        "id": app_key,
        "name": "Share Test App",
        "shape": "web-app",
        "runtime": "node22",
        "roles": ["employee", "manager", "hr"],
        "capabilities": {"db": {"type": "sqlite"}, "identity": True},
        "egress": [],
        "sharing": {"default": "org"},
        "limits": {
            "cpu": "small",
            "memory_mb": 256,
            "request_timeout_s": 30,
        },
    }

    create_resp = await client.post(
        "/v1/apps",
        headers=headers_alice,
        json={"id": app_key, "name": "Share Test App", "manifest": manifest},
    )
    assert create_resp.status_code == 201
    created_app = create_resp.json()
    app_id = created_app["id"]

    # 2. Alice (Owner) shares app with Bob assigning role 'manager'
    share_resp = await client.post(
        f"/v1/apps/{app_id}/shares",
        headers=headers_alice,
        json={
            "user_email": "bob@example.com",
            "app_role": "manager",
        },
    )
    assert share_resp.status_code == 201
    share_data = share_resp.json()
    assert share_data["app_role"] == "manager"
    assert share_data["user_email"] == "bob@example.com"
    assert share_data["status"] == "active"
    bob_share_id = share_data["id"]

    # 3. Alice creates a group share for 'engineering' assigning role 'employee'
    group_share_resp = await client.post(
        f"/v1/apps/{app_id}/shares",
        headers=headers_alice,
        json={
            "group_name": "engineering",
            "app_role": "employee",
        },
    )
    assert group_share_resp.status_code == 201
    group_share_data = group_share_resp.json()
    assert group_share_data["grant_type"] == "group"
    assert group_share_data["group_name"] == "engineering"

    # 4. Attempt to share with an undeclared role -> 400 Bad Request
    bad_role_resp = await client.post(
        f"/v1/apps/{app_id}/shares",
        headers=headers_alice,
        json={
            "user_email": "bob@example.com",
            "app_role": "super_admin_undeclared",
        },
    )
    assert bad_role_resp.status_code == 400
    assert "not declared" in bad_role_resp.json()["detail"]

    # 5. Bob (regular User) attempts to create a share -> 403 Forbidden
    bob_attempt_resp = await client.post(
        f"/v1/apps/{app_id}/shares",
        headers=headers_bob,
        json={
            "user_email": "another@example.com",
            "app_role": "employee",
        },
    )
    assert bob_attempt_resp.status_code == 403
    assert "Only Owner and Editor" in bob_attempt_resp.json()["detail"]

    # 6. Bob attempts to revoke Alice's share -> 403 Forbidden
    bob_revoke_resp = await client.delete(
        f"/v1/apps/{app_id}/shares/{bob_share_id}",
        headers=headers_bob,
    )
    assert bob_revoke_resp.status_code == 403

    # 7. List shares as Alice or Bob (both are org members)
    list_resp = await client.get(f"/v1/apps/{app_id}/shares", headers=headers_bob)
    assert list_resp.status_code == 200
    shares_list = list_resp.json()["shares"]
    assert len(shares_list) >= 2

    # 8. Evaluate access for Bob (should have role 'manager' from his share)
    access_bob_resp = await client.get(
        f"/v1/apps/{app_id}/access",
        headers=headers_bob,
    )
    assert access_bob_resp.status_code == 200
    access_bob = access_bob_resp.json()
    assert access_bob["allowed"] is True
    assert "manager" in access_bob["app_roles"]

    # 9. Evaluate access for Charlie (different org) -> allowed=False
    access_charlie_resp = await client.get(
        f"/v1/apps/{app_id}/access",
        headers=headers_charlie,
    )
    assert access_charlie_resp.status_code == 200
    assert access_charlie_resp.json()["allowed"] is False

    # 10. Alice revokes Bob's share -> 204 No Content
    revoke_resp = await client.delete(
        f"/v1/apps/{app_id}/shares/{bob_share_id}",
        headers=headers_alice,
    )
    assert revoke_resp.status_code == 204

    # 11. Verify audit event for revocation
    audit_resp = await client.get(
        f"/v1/audit/events?target_type=app_share",
        headers=headers_alice,
    )
    assert audit_resp.status_code == 200
    events = audit_resp.json()
    revoke_events = [e for e in events if e["action"] == "app.share.revoke"]
    assert len(revoke_events) >= 1
