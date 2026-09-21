"""
Test Database Constraints & Indexes Rejection of Bad Data
"""
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta
import pytest
from sqlalchemy.exc import IntegrityError

# Ensure src is in python path
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from db.session import AsyncSessionLocal
from db.models import Organization, User, App, AppShare, AppVersion


@pytest.mark.asyncio
async def test_organization_status_check_constraint():
    async with AsyncSessionLocal() as session:
        bad_org = Organization(
            slug=f"bad-org-{uuid.uuid4().hex[:8]}",
            name="Bad Org",
            status="invalid_status",  # Must violate CHECK (status IN ('active', 'suspended', 'deleting'))
        )
        session.add(bad_org)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_user_unique_identity_constraint():
    issuer = "https://accounts.google.com"
    subject = f"sub-{uuid.uuid4().hex}"

    async with AsyncSessionLocal() as session:
        u1 = User(
            email=f"user1-{uuid.uuid4().hex[:8]}@example.com",
            identity_issuer=issuer,
            identity_subject=subject,
        )
        session.add(u1)
        await session.flush()

        u2 = User(
            email=f"user2-{uuid.uuid4().hex[:8]}@example.com",
            identity_issuer=issuer,
            identity_subject=subject,  # Duplicate identity pair
        )
        session.add(u2)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_user_case_insensitive_email_unique_index():
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"

    async with AsyncSessionLocal() as session:
        u1 = User(email=email.lower())
        session.add(u1)
        await session.flush()

        u2 = User(email=email.upper())  # Should violate uq_users_email_ci
        session.add(u2)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_app_share_expiry_check_constraint():
    async with AsyncSessionLocal() as session:
        # Create an app first
        app = App(
            app_key=f"app-{uuid.uuid4().hex[:8]}",
            name="Test App",
        )
        session.add(app)
        await session.flush()

        now = datetime.utcnow()
        # Invalid share: expires_at <= granted_at
        bad_share = AppShare(
            app_id=app.id,
            granted_at=now,
            expires_at=now - timedelta(hours=1),
        )
        session.add(bad_share)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_app_version_published_has_timestamp_check_constraint():
    async with AsyncSessionLocal() as session:
        app = App(
            app_key=f"app-{uuid.uuid4().hex[:8]}",
            name="Test App",
        )
        session.add(app)
        await session.flush()

        # Status is 'published' but published_at is NULL
        bad_version = AppVersion(
            app_id=app.id,
            version_number=99,
            status="published",
            source_artifact_ref="ref",
            manifest={},
            db_snapshot_ref="snapshot",
            published_at=None,
        )
        session.add(bad_version)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
