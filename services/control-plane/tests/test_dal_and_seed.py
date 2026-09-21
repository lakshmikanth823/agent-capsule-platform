"""
Test Data Access Layer (DAL) and Seed Loading
"""
import sys
from pathlib import Path
import pytest

# Ensure src is in python path
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from db.session import db_context
from db.seed import seed_database
from db.dal import OrganizationDAL, UserDAL, AppDAL, AppVersionDAL, AppShareDAL, AuditDAL


@pytest.mark.asyncio
async def test_seed_loading_and_dal_queries():
    # 1. Run seed script
    await seed_database()

    # 2. Query seeded data through DAL
    async with db_context() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        version_dal = AppVersionDAL(session)
        share_dal = AppShareDAL(session)
        audit_dal = AuditDAL(session)

        # Verify Organization
        org = await org_dal.get_by_slug("acme-corp")
        assert org is not None
        assert org.name == "Acme Corp"
        assert org.status == "active"

        # Verify Users
        alice = await user_dal.get_by_email("alice@example.com")
        assert alice is not None
        assert alice.display_name == "Alice Owner"

        bob = await user_dal.get_by_email("bob@example.com")
        assert bob is not None
        assert bob.display_name == "Bob Colleague"

        # Verify Org Membership
        members = await user_dal.get_org_members(org.id)
        assert len(members) >= 2
        roles = {m.user_id: m.platform_role for m in members}
        assert roles[alice.id] == "owner"
        assert roles[bob.id] == "user"

        # Verify App
        app = await app_dal.get_by_key(org.id, "leave-tracker")
        assert app is not None
        assert app.shape == "web-app"
        assert app.runtime == "node22"
        assert app.owner_user_id == alice.id

        # Verify Version
        versions = await version_dal.list_for_app(app.id)
        assert len(versions) >= 1
        v1 = versions[0]
        assert v1.version_number == 1
        assert v1.status == "published"
        assert v1.db_snapshot_ref == "capsules/leave-tracker/snapshots/v1-init.sqlite"
        assert v1.published_at is not None

        # Verify App Share
        shares = await share_dal.list_shares_for_app(app.id)
        bob_share = next((s for s in shares if s.user_id == bob.id), None)
        assert bob_share is not None
        assert bob_share.app_role == "employee"
        assert bob_share.status == "active"

        # Verify Audit Events
        events = await audit_dal.list_events(organization_id=org.id, app_id=app.id)
        assert len(events) >= 1
        assert any(e.action == "app.publish" for e in events)
