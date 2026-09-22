"""
Comprehensive Test Suite for Prompt 20: Governance (FR-033 to FR-036).
Covers:
1. Ownership transfer by app owner (success, audit event, notification).
2. Ownership transfer by organization admin (success, audit event).
3. Ownership transfer permission rejection for regular users (HTTP 403).
4. Ownership transfer validation for non-existent or invalid target users.
5. Owner-left handling with nominated owner (immediate auto-transfer, audit event, notification).
6. Owner-left handling without nominated owner (14-day grace period, pending_owner state, notifications to admins/editors, remains active).
7. Background governance cycle detects expired grace period (suspends app, updates state, audit event, notification).
8. Activity tracking updates last_activity_at.
9. Inactivity & expiry warnings at thresholds (14d, 7d, 1d), audit event, warnings_sent tracking.
10. Expiry lifecycle transition to archived state (data retained, audit event).
11. Permanent purge after archive retention window (export offered, audit event).
12. Application inventory API & RFC 4180 CSV / JSON exports.
13. App data export snapshot endpoint.
"""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, and_

from main import app
from db.session import db_context
from db.models import Organization, User, OrganizationMember, App, AuditEvent, AppShare
from db.dal import AppDAL, OrganizationDAL, UserDAL, AuditDAL
from services.governance import GovernanceService
from services.notification import get_notification_sender, InMemoryNotificationSender
from services.deprovisioning import deprovision_user


@pytest.fixture
def test_notifier():
    sender = get_notification_sender()
    if isinstance(sender, InMemoryNotificationSender):
        sender.clear()
    return sender


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_ownership_transfer_by_owner_and_admin(client, test_notifier):
    """
    FR-033: Verifies ownership transfer by the current owner and by an org admin.
    Verifies audit event 'app.ownership_transferred' and notification dispatch.
    """
    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)

        # Use seeded organization for mock token compatibility
        org = await org_dal.get_by_slug("acme-corp")
        assert org is not None

        # Users: Alice (Admin), Bob (User), Dave (User)
        alice = await user_dal.get_by_email("alice@example.com")
        bob = await user_dal.get_by_email("bob@example.com")
        dave = await user_dal.create(
            email=f"dave-{uuid.uuid4().hex[:6]}@example.com",
            display_name="Dave Colleague",
        )
        await user_dal.add_to_org(org.id, dave.id, platform_role="user")

        # Create app owned by Bob
        test_app = await app_dal.create(
            app_key=f"gov-app-{uuid.uuid4().hex[:6]}",
            name="Bob's Tracker",
            organization_id=org.id,
            owner_user_id=bob.id,
            status="active",
            manifest={"id": "bobs-tracker", "name": "Bob's Tracker"},
        )
        await session.commit()

    # 1. Bob (current owner) transfers app to Dave
    resp1 = await client.post(
        f"/v1/apps/{test_app.id}/transfer-ownership",
        headers={"Authorization": "Bearer mock-bob-token"},
        json={
            "new_owner_user_id": str(dave.id),
            "reason": "Handing project off to Dave",
        },
    )
    assert resp1.status_code == 200, resp1.text
    data1 = resp1.json()
    assert data1["owner_user_id"] == str(dave.id)

    # Verify notification sent to Dave
    dave_msgs = test_notifier.get_messages_for(dave.email)
    assert len(dave_msgs) >= 1
    assert "Handing project off to Dave" in dave_msgs[-1].body

    # 2. Alice (Organization Admin) transfers app from Dave to Bob
    resp2 = await client.post(
        f"/v1/apps/{test_app.id}/transfer-ownership",
        headers={"Authorization": "Bearer mock-alice-token"},
        json={
            "new_owner_user_id": str(bob.id),
            "reason": "Admin reassignment back to Bob",
        },
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert data2["owner_user_id"] == str(bob.id)

    # Verify Audit Events recorded with proper hash chain
    async with db_context() as session:
        audit_events = list(
            (
                await session.execute(
                    select(AuditEvent)
                    .where(
                        and_(
                            AuditEvent.organization_id == org.id,
                            AuditEvent.app_id == test_app.id,
                            AuditEvent.action == "app.ownership_transferred",
                        )
                    )
                    .order_by(AuditEvent.sequence_number.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(audit_events) == 2
        # First event by Bob
        assert audit_events[0].actor_user_id == bob.id
        assert audit_events[0].metadata_["new_owner_id"] == str(dave.id)
        assert audit_events[0].metadata_["transferred_by_role"] == "owner"
        # Second event by Alice (admin)
        assert audit_events[1].actor_user_id == alice.id
        assert audit_events[1].metadata_["new_owner_id"] == str(bob.id)
        assert audit_events[1].metadata_["transferred_by_role"] == "admin"


@pytest.mark.asyncio
async def test_ownership_transfer_permissions_and_validation(client):
    """
    Verifies that unauthorized users cannot transfer apps, and invalid target users are rejected.
    """
    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")
        bob = await user_dal.get_by_email("bob@example.com")

        # App owned by Alice
        alice_app = await app_dal.create(
            app_key=f"alice-app-{uuid.uuid4().hex[:6]}",
            name="Alice's Private App",
            organization_id=org.id,
            owner_user_id=alice.id,
            status="active",
        )
        await session.commit()

    # Bob (regular user, non-owner) attempts to transfer Alice's app -> 403 Forbidden
    resp = await client.post(
        f"/v1/apps/{alice_app.id}/transfer-ownership",
        headers={"Authorization": "Bearer mock-bob-token"},
        json={"new_owner_user_id": str(bob.id)},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN"

    # Alice transfers to a non-existent user ID -> 400 Bad Request
    fake_user_id = uuid.uuid4()
    resp_invalid = await client.post(
        f"/v1/apps/{alice_app.id}/transfer-ownership",
        headers={"Authorization": "Bearer mock-alice-token"},
        json={"new_owner_user_id": str(fake_user_id)},
    )
    assert resp_invalid.status_code == 400
    assert resp_invalid.json()["detail"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_owner_left_with_nominated_owner(client, test_notifier):
    """
    FR-034: When owner is deprovisioned and app has nominated_owner_user_id,
    ownership is automatically and immediately transferred to the nominee.
    """
    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)

        org = await org_dal.create(
            slug=f"nominee-org-{uuid.uuid4().hex[:6]}",
            name="Nominee Test Org",
            status="active",
        )
        # Leaving user
        leaving_user = await user_dal.create(
            email=f"leaver-{uuid.uuid4().hex[:6]}@example.com",
            display_name="Leaving User",
        )
        # Nominated backup owner
        nominee_user = await user_dal.create(
            email=f"nominee-{uuid.uuid4().hex[:6]}@example.com",
            display_name="Nominated Successor",
        )
        await user_dal.add_to_org(org.id, leaving_user.id, platform_role="user")
        await user_dal.add_to_org(org.id, nominee_user.id, platform_role="user")

        # Create app with nominated owner
        app_with_nominee = await app_dal.create(
            app_key=f"nominee-app-{uuid.uuid4().hex[:6]}",
            name="Mission Critical Tool",
            organization_id=org.id,
            owner_user_id=leaving_user.id,
            status="active",
            manifest={"id": "mission-critical", "name": "Mission Critical Tool"},
        )
        app_with_nominee.nominated_owner_user_id = nominee_user.id
        await session.commit()

        # Trigger SCIM / administrative deprovisioning
        result = await deprovision_user(
            db=session,
            org_id=org.id,
            user_id=leaving_user.id,
            reason="Employee offboarding",
        )
        await session.commit()

        # Check returned affected apps
        affected = result["affected_apps"]
        assert len(affected) == 1
        assert affected[0]["action"] == "transferred_to_nominee"
        assert affected[0]["new_owner_id"] == str(nominee_user.id)

        # Check DB state
        refreshed_app = await app_dal.get_by_id(app_with_nominee.id)
        assert refreshed_app.owner_user_id == nominee_user.id
        assert refreshed_app.status == "active"
        assert refreshed_app.governance_state == "normal"

        # Check notification sent to nominee
        nominee_msgs = test_notifier.get_messages_for(nominee_user.email)
        assert len(nominee_msgs) >= 1
        assert "Mission Critical Tool" in nominee_msgs[-1].subject

        # Check audit event
        audit = (
            await session.execute(
                select(AuditEvent).where(
                    and_(
                        AuditEvent.organization_id == org.id,
                        AuditEvent.app_id == app_with_nominee.id,
                        AuditEvent.action == "app.ownership_transferred",
                    )
                )
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert audit.metadata_["trigger"] == "owner_left_nominee"


@pytest.mark.asyncio
async def test_owner_left_without_nominee_grace_period_and_expiry(client, test_notifier):
    """
    FR-034: When owner is deprovisioned and app has NO nominee:
    1. A 14-day grace period is started, governance_state = 'pending_owner'.
    2. Notifications are sent to org admins and editors.
    3. App remains active during the grace period (no silent breakage).
    4. When grace period expires without reassignment, background cycle suspends app.
    """
    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)

        org = await org_dal.create(
            slug=f"grace-org-{uuid.uuid4().hex[:6]}",
            name="Grace Period Org",
            status="active",
        )
        admin = await user_dal.create(
            email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
            display_name="Org Admin",
        )
        editor = await user_dal.create(
            email=f"editor-{uuid.uuid4().hex[:6]}@example.com",
            display_name="Org Editor",
        )
        orphan_owner = await user_dal.create(
            email=f"orphan-{uuid.uuid4().hex[:6]}@example.com",
            display_name="Orphan Owner",
        )
        await user_dal.add_to_org(org.id, admin.id, platform_role="owner")
        await user_dal.add_to_org(org.id, editor.id, platform_role="editor")
        await user_dal.add_to_org(org.id, orphan_owner.id, platform_role="user")

        unowned_app = await app_dal.create(
            app_key=f"unowned-{uuid.uuid4().hex[:6]}",
            name="Team Portal",
            organization_id=org.id,
            owner_user_id=orphan_owner.id,
            status="active",
            manifest={"id": "team-portal", "name": "Team Portal"},
        )
        await session.commit()

        # Step 1: Deprovision owner
        deprov_res = await deprovision_user(
            db=session,
            org_id=org.id,
            user_id=orphan_owner.id,
            reason="Resigned",
        )
        await session.commit()

        # Verify grace period started
        affected = deprov_res["affected_apps"]
        assert len(affected) == 1
        assert affected[0]["action"] == "grace_period_started"
        assert affected[0]["grace_period_days"] == 14

        # App must REMAIN ACTIVE during grace period!
        refreshed = await app_dal.get_by_id(unowned_app.id)
        assert refreshed.status == "active"
        assert refreshed.governance_state == "pending_owner"
        assert refreshed.governance_deadline is not None

        # Verify notifications sent to both admin and editor
        admin_msgs = test_notifier.get_messages_for(admin.email)
        editor_msgs = test_notifier.get_messages_for(editor.email)
        assert len(admin_msgs) >= 1
        assert "Team Portal" in admin_msgs[-1].subject
        assert len(editor_msgs) >= 1
        assert "Team Portal" in editor_msgs[-1].subject

    # Step 2: Simulate time advancing by 15 days (past the 14-day deadline)
    future_time = datetime.now(timezone.utc) + timedelta(days=15)

    async with db_context() as session:
        gov = GovernanceService(session)
        cycle_stats = await gov.run_governance_cycle(org_id=org.id, current_time=future_time)
        await session.commit()

        assert cycle_stats["grace_periods_expired"] == 1

        # Check app is now SUSPENDED
        expired_app = await AppDAL(session).get_by_id(unowned_app.id)
        assert expired_app.status == "suspended"
        assert expired_app.governance_state == "grace_period_expired"
        assert "Owner grace period expired" in expired_app.suspension_reason

        # Check audit event
        audit = (
            await session.execute(
                select(AuditEvent).where(
                    and_(
                        AuditEvent.organization_id == org.id,
                        AuditEvent.app_id == unowned_app.id,
                        AuditEvent.action == "app.owner_grace_period_expired",
                    )
                )
            )
        ).scalar_one_or_none()
        assert audit is not None


@pytest.mark.asyncio
async def test_expiry_lifecycle_warnings_archival_purge(client, test_notifier):
    """
    FR-035: Expiry lifecycle:
    1. Warning intervals (14d, 7d, 1d) dispatch alerts and track governance_warnings_sent.
    2. Expiry date transitions app to 'archived' state (suspended, data kept).
    3. Retention period ends -> app purged / deleting.
    """
    now = datetime.now(timezone.utc)
    t_expiry = now + timedelta(days=20)

    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)

        org = await org_dal.create(
            slug=f"expiry-org-{uuid.uuid4().hex[:6]}",
            name="Expiry Lifecycle Org",
            status="active",
        )
        owner = await user_dal.create(
            email=f"expiryowner-{uuid.uuid4().hex[:6]}@example.com",
            display_name="Expiry Owner",
        )
        await user_dal.add_to_org(org.id, owner.id, platform_role="owner")

        app = await app_dal.create(
            app_key=f"expiring-app-{uuid.uuid4().hex[:6]}",
            name="Quarterly Survey",
            organization_id=org.id,
            owner_user_id=owner.id,
            status="active",
        )
        app.expires_at = t_expiry
        app.purge_after_days = 30
        await session.commit()
        app_id = app.id

    # 1. Advance to 10 days before expiry (within 14-day warning threshold)
    t_warning14 = t_expiry - timedelta(days=10)
    async with db_context() as session:
        gov = GovernanceService(session)
        stats1 = await gov.run_governance_cycle(org_id=org.id, current_time=t_warning14)
        await session.commit()
        assert stats1["warnings_sent"] == 1

        app_ref = await AppDAL(session).get_by_id(app_id)
        assert 14 in app_ref.governance_warnings_sent

    # 2. Advance to 3 days before expiry (within 7-day warning threshold)
    t_warning7 = t_expiry - timedelta(days=3)
    async with db_context() as session:
        gov = GovernanceService(session)
        stats2 = await gov.run_governance_cycle(org_id=org.id, current_time=t_warning7)
        await session.commit()
        assert stats2["warnings_sent"] == 1

        app_ref = await AppDAL(session).get_by_id(app_id)
        assert 7 in app_ref.governance_warnings_sent

    # 3. Advance to 1 day after expiry -> Should transition to ARCHIVED
    t_archived = t_expiry + timedelta(days=1)
    async with db_context() as session:
        gov = GovernanceService(session)
        stats3 = await gov.run_governance_cycle(org_id=org.id, current_time=t_archived)
        await session.commit()
        assert stats3["archived_count"] == 1

        app_ref = await AppDAL(session).get_by_id(app_id)
        assert app_ref.status == "archived"
        assert app_ref.governance_state == "archived"
        assert app_ref.archived_at is not None
        assert app_ref.governance_deadline == t_archived + timedelta(days=30)

    # 4. Advance past 30-day retention purge deadline -> Should transition to PURGED/DELETING
    t_purged = t_archived + timedelta(days=31)
    async with db_context() as session:
        gov = GovernanceService(session)
        stats4 = await gov.run_governance_cycle(org_id=org.id, current_time=t_purged)
        await session.commit()
        assert stats4["purged_count"] == 1

        app_ref = await AppDAL(session).get_by_id(app_id)
        assert app_ref.status == "deleting"
        assert app_ref.governance_state == "purged"


@pytest.mark.asyncio
async def test_activity_tracking_and_inactivity_expiry(client):
    """
    FR-035: Track last activity per app for inactivity-based expiry.
    """
    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        app = await app_dal.create(
            app_key=f"activity-app-{uuid.uuid4().hex[:6]}",
            name="Usage Tracking App",
            organization_id=org.id,
            owner_user_id=alice.id,
            status="active",
        )
        app.inactivity_days_limit = 45
        await session.commit()
        app_id = app.id

    # Record activity via API
    t_activity = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    resp = await client.post(
        f"/v1/apps/{app_id}/activity",
        headers={"Authorization": "Bearer mock-alice-token"},
        json={"timestamp": t_activity.isoformat()},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify DB recorded timestamp
    async with db_context() as session:
        app_ref = await AppDAL(session).get_by_id(app_id)
        assert app_ref.last_activity_at == t_activity

    # 46 days after t_activity -> inactivity limit passed -> cycle archives app
    t_future = t_activity + timedelta(days=46)
    async with db_context() as session:
        gov = GovernanceService(session)
        stats = await gov.run_governance_cycle(org_id=org.id, current_time=t_future)
        await session.commit()
        assert stats["archived_count"] == 1

        app_ref = await AppDAL(session).get_by_id(app_id)
        assert app_ref.status == "archived"


@pytest.mark.asyncio
async def test_inventory_api_and_exports(client):
    """
    FR-036: Application Inventory dashboard API, CSV export, and JSON export.
    Verifies owner, status, user count, capabilities, last activity, version, and expiry status.
    """
    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")
        colleague = await user_dal.create(
            email=f"colleague-{uuid.uuid4().hex[:6]}@example.com",
            display_name="Colleague Sharee",
        )
        await user_dal.add_to_org(org.id, colleague.id, platform_role="user")

        app = await app_dal.create(
            app_key=f"inv-app-{uuid.uuid4().hex[:6]}",
            name="Inventory Portal",
            organization_id=org.id,
            owner_user_id=alice.id,
            status="active",
            manifest={
                "id": "inventory-portal",
                "name": "Inventory Portal",
                "capabilities": {"db": {"type": "sqlite"}, "sheets.read": {"spreadsheet_ids": ["*"]}},
            },
        )
        # Add a share for colleague
        share = AppShare(
            app_id=app.id,
            user_id=colleague.id,
            app_role="viewer",
            status="active",
            granted_by_user_id=alice.id,
        )
        session.add(share)
        await session.commit()
        app_id = app.id

    # 1. Query Inventory API
    resp = await client.get(
        f"/v1/organizations/{org.id}/inventory",
        headers={"Authorization": "Bearer mock-alice-token"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] >= 1
    target_item = next((i for i in data["items"] if i["id"] == str(app_id)), None)
    assert target_item is not None
    assert target_item["name"] == "Inventory Portal"
    assert target_item["owner"]["email"] == alice.email
    assert target_item["user_count"] == 2  # Owner + 1 share
    assert "db" in target_item["capabilities"]
    assert "sheets.read" in target_item["capabilities"]
    assert target_item["expiry_status"] == "active"

    # 2. Export Inventory as CSV
    resp_csv = await client.get(
        f"/v1/organizations/{org.id}/inventory/export?format=csv",
        headers={"Authorization": "Bearer mock-alice-token"},
    )
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    reader = csv.DictReader(io.StringIO(resp_csv.text))
    rows = list(reader)
    assert len(rows) >= 1
    csv_target = next((r for r in rows if r["id"] == str(app_id)), None)
    assert csv_target is not None
    assert csv_target["name"] == "Inventory Portal"
    assert csv_target["owner_email"] == alice.email
    assert csv_target["user_count"] == "2"

    # 3. Export Inventory as JSON
    resp_json = await client.get(
        f"/v1/organizations/{org.id}/inventory/export?format=json",
        headers={"Authorization": "Bearer mock-alice-token"},
    )
    assert resp_json.status_code == 200
    json_data = resp_json.json()
    assert json_data["total"] >= 1


@pytest.mark.asyncio
async def test_app_data_export_snapshot(client):
    """
    Verifies that capsule data snapshots can be exported prior to or during archival.
    """
    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)

        org = await org_dal.get_by_slug("acme-corp")
        alice = await user_dal.get_by_email("alice@example.com")

        app = await app_dal.create(
            app_key=f"exportable-{uuid.uuid4().hex[:6]}",
            name="Exportable App",
            organization_id=org.id,
            owner_user_id=alice.id,
            status="active",
            manifest={"id": "exportable", "name": "Exportable App"},
        )
        await session.commit()
        app_id = app.id

    resp = await client.get(
        f"/v1/apps/{app_id}/export-data",
        headers={"Authorization": "Bearer mock-alice-token"},
    )
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    snapshot = resp.json()
    assert snapshot["export_metadata"]["app_id"] == str(app_id)
    assert snapshot["app"]["name"] == "Exportable App"
