"""
conftest.py — Session-scoped database state reset.

Runs once at the START of each pytest session to clean up state left by
previous test runs against the shared Postgres database. Specifically:
- Resumes any suspended organizations and sets high quota limits (via env_profile.quotas)
- Clears token/session revocation timestamps on orgs and users
- Resumes any suspended apps
- Deletes apps created by tests (keeping only the seed app 'leave-tracker')
"""
import sys
import asyncio
import socket
from pathlib import Path

import pytest

# Make sure src is on the path (same as the app itself)
_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from sqlalchemy import update, delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from db.session import AsyncSessionLocal
from db.models import Organization, User, App


def _is_postgres_available() -> bool:
    """Check whether PostgreSQL is reachable on its configured host and port."""
    try:
        from core.config import settings
        url = getattr(settings, "DATABASE_URL", "")
        host = "localhost"
        port = 5432
        if "@" in url:
            host_port = url.split("@")[1].split("/")[0]
            if ":" in host_port:
                host, port_str = host_port.split(":")
                port = int(port_str)
            else:
                host = host_port
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    """Gracefully skip tests that require a live PostgreSQL instance when Postgres is unreachable."""
    if not _is_postgres_available():
        skip_pg = pytest.mark.skip(
            reason=(
                "PostgreSQL instance is not reachable at localhost:5432. "
                "Start with 'docker compose up -d postgres' to run control-plane DB integration tests."
            )
        )
        for item in items:
            if "test_health.py" not in str(item.fspath):
                item.add_marker(skip_pg)


async def _reset_db_state():
    """Direct DB reset — does not go through the API."""
    session: AsyncSession = AsyncSessionLocal()
    try:
        # 1. Resume all suspended organizations, clear revocation timestamps,
        #    and set a high apps_per_user quota so tests don't hit the limit.
        result = await session.execute(select(Organization))
        orgs = result.scalars().all()
        for org in orgs:
            profile = dict(org.environment_profile or {})
            # Quotas live inside env_profile["quotas"] per quota_service.py
            quotas = dict(profile.get("quotas") or {})
            quotas["apps_per_user"] = 200
            profile["quotas"] = quotas
            org.status = "active"
            org.suspended_at = None
            org.suspended_by_user_id = None
            org.suspension_reason = None
            org.tokens_revoked_at = None
            org.sessions_revoked_at = None
            org.environment_profile = profile
            # Force SQLAlchemy to detect the JSON mutation
            flag_modified(org, "environment_profile")

        # 2. Clear user-level revocation timestamps so old sessions/tokens are valid again
        await session.execute(
            update(User).values(
                tokens_revoked_at=None,
                sessions_revoked_at=None,
            )
        )

        # 3. Resume all suspended apps
        await session.execute(
            update(App)
            .where(App.status == "suspended")
            .values(
                status="active",
                suspended_at=None,
                suspended_by_user_id=None,
                suspension_reason=None,
            )
        )

        # 4. Delete all apps EXCEPT the seed app (leave-tracker) so quota counters reset
        await session.execute(text("SET LOCAL capsule.allow_retention_purge = 'on'"))
        await session.execute(
            delete(App).where(App.app_key != "leave-tracker")
        )

        await session.commit()
        print("\n[conftest] + DB state reset complete — orgs active, quotas raised to 200, test apps deleted.")
    except Exception as e:
        await session.rollback()
        print(f"\n[conftest] - DB reset error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await session.close()


@pytest.fixture(scope="session", autouse=True)
def reset_db_state_session():
    """Runs once at the start of the test session to ensure a clean DB state."""
    if not _is_postgres_available():
        print("\n[conftest] Note: PostgreSQL is not reachable at localhost:5432. DB reset skipped.")
        yield
        return
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_reset_db_state())
    loop.close()
    yield
