"""
Database Seed Script for Software Capsule Platform Control Plane
Seeds:
- 1 Organization (Acme Corp)
- 2 Users (Alice - owner, Bob - colleague)
- 1 Sample App (leave-tracker)
- 1 App Version (Version 1 with baseline SQLite snapshot reference)
- 1 App Share (Bob assigned 'employee' role)
"""
import sys
import asyncio
from pathlib import Path
from datetime import datetime

# Ensure src is in python path
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from db.session import get_db_session
from db.dal import OrganizationDAL, UserDAL, AppDAL, AppVersionDAL, AppShareDAL, AuditDAL


async def seed_database():
    print("[*] Seeding database...")
    async with get_db_session() as session:
        org_dal = OrganizationDAL(session)
        user_dal = UserDAL(session)
        app_dal = AppDAL(session)
        version_dal = AppVersionDAL(session)
        share_dal = AppShareDAL(session)
        audit_dal = AuditDAL(session)

        # 1. Organization: Acme Corp
        org = await org_dal.get_by_slug("acme-corp")
        if not org:
            org = await org_dal.create(
                slug="acme-corp",
                name="Acme Corp",
                status="active",
                environment_profile={
                    "allowed_shapes": ["web-app"],
                    "allowed_runtimes": ["node22"],
                    "default_sharing": "org",
                },
            )
            print(f"  + Created organization: {org.name} ({org.id})")

        # 2. Users: Alice (Owner) and Bob (Colleague)
        alice = await user_dal.get_by_email("alice@example.com")
        if not alice:
            alice = await user_dal.create(
                email="alice@example.com",
                display_name="Alice Owner",
                identity_subject="google-oauth2|alice-12345",
                identity_issuer="https://accounts.google.com",
                status="active",
            )
            await user_dal.add_to_org(org.id, alice.id, platform_role="owner")
            print(f"  + Created owner user: {alice.email} ({alice.id})")

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
            print(f"  + Created colleague user: {bob.email} ({bob.id})")

        # 3. Sample App: leave-tracker
        app = await app_dal.get_by_key(org.id, "leave-tracker")
        if not app:
            app = await app_dal.create(
                app_key="leave-tracker",
                name="Leave Tracker",
                organization_id=org.id,
                owner_user_id=alice.id,
                description="Sample leave management capsule application",
                shape="web-app",
                runtime="node22",
                status="active",
                manifest={
                    "apiVersion": "capsule/v1alpha1",
                    "id": "leave-tracker",
                    "name": "Leave Tracker",
                    "shape": "web-app",
                    "runtime": "node22",
                    "roles": ["employee", "manager", "hr"],
                    "capabilities": {
                        "db": {"type": "sqlite"},
                        "identity": True,
                    },
                },
            )
            print(f"  + Created app: {app.name} ({app.id})")

        # 4. App Version: Version 1 with baseline SQLite snapshot reference
        versions = await version_dal.list_for_app(app.id)
        if not versions:
            version1 = await version_dal.create(
                app_id=app.id,
                version_number=1,
                status="published",
                source_artifact_ref="capsules/leave-tracker/artifacts/v1.tar.gz",
                manifest=app.manifest,
                db_snapshot_ref="capsules/leave-tracker/snapshots/v1-init.sqlite",
                publisher_user_id=alice.id,
                publisher_agent="capsule-cli/0.1.0",
                change_description="Initial deployment of Leave Tracker",
                published_at=datetime.utcnow(),
            )
            await app_dal.set_current_version(app.id, version1.id, version1.published_at)
            print(f"  + Created app version: v{version1.version_number} ({version1.id})")

        # 5. App Share: Bob granted 'employee' role
        shares = await share_dal.list_shares_for_app(app.id)
        if not any(s.user_id == bob.id for s in shares):
            share = await share_dal.create_share(
                app_id=app.id,
                user_id=bob.id,
                app_role="employee",
                status="active",
                granted_by_user_id=alice.id,
            )
            print(f"  + Granted share to {bob.email} with role '{share.app_role}'")

        # Set default share policy
        await share_dal.set_share_policy(
            app_id=app.id,
            default_scope="org",
            external_users_allowed=False,
            updated_by_user_id=alice.id,
        )

        # 6. Audit Event
        await audit_dal.record_event(
            action="app.publish",
            outcome="success",
            organization_id=org.id,
            app_id=app.id,
            actor_user_id=alice.id,
            actor_agent="capsule-cli/0.1.0",
            target_type="app_version",
            target_id=app.current_version_id,
            metadata={"version": 1, "note": "Initial seeded deployment"},
        )
        print("  + Recorded audit event for initial deployment")

    print("[*] Database seeded successfully!")


if __name__ == "__main__":
    asyncio.run(seed_database())
