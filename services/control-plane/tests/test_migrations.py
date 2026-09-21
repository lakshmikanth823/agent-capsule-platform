"""
Test Alembic Migrations: Upgrade to Head, Downgrade to Base, and Re-upgrade
"""
import sys
from pathlib import Path
import pytest
from sqlalchemy import inspect

# Ensure src is in python path
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from alembic import command
from alembic.config import Config
from db.session import sync_engine


@pytest.fixture(scope="module")
def alembic_cfg():
    root_dir = Path(__file__).resolve().parent.parent
    alembic_ini_path = root_dir / "alembic.ini"
    cfg = Config(str(alembic_ini_path))
    cfg.set_main_option("script_location", str(root_dir / "alembic"))
    return cfg


def test_migrations_lifecycle(alembic_cfg):
    expected_tables = {
        "organizations",
        "users",
        "organization_members",
        "apps",
        "app_shares",
        "app_share_policies",
        "app_versions",
        "audit_events",
        "capability_approvals",
    }

    # 1. Downgrade to base (clean slate)
    command.downgrade(alembic_cfg, "base")

    inspector = inspect(sync_engine)
    current_tables = set(inspector.get_table_names())
    for t in expected_tables:
        assert t not in current_tables, f"Table {t} should not exist after downgrade to base"

    # 2. Upgrade to head
    command.upgrade(alembic_cfg, "head")

    inspector = inspect(sync_engine)
    current_tables = set(inspector.get_table_names())
    for t in expected_tables:
        assert t in current_tables, f"Table {t} should exist after upgrade to head"

    # 3. Downgrade to base again
    command.downgrade(alembic_cfg, "base")
    inspector = inspect(sync_engine)
    current_tables = set(inspector.get_table_names())
    for t in expected_tables:
        assert t not in current_tables, f"Table {t} should not exist after second downgrade"

    # 4. Final upgrade to head for subsequent tests
    command.upgrade(alembic_cfg, "head")
    inspector = inspect(sync_engine)
    current_tables = set(inspector.get_table_names())
    assert expected_tables.issubset(current_tables)
