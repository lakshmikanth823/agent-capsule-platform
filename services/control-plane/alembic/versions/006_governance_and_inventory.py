"""Governance and inventory lifecycle columns for apps

Revision ID: 006_governance_and_inventory
Revises: 005_audit_hash_chain
Create Date: 2026-09-22 10:45:00.000000

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_governance_and_inventory"
down_revision: Union[str, None] = "005_audit_hash_chain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    -- 1. Add governance and activity tracking columns to apps
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS nominated_owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL;
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ NULL;
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL;
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS inactivity_days_limit INTEGER NULL;
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS governance_state VARCHAR(30) NOT NULL DEFAULT 'normal';
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS governance_deadline TIMESTAMPTZ NULL;
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS governance_warnings_sent JSONB NOT NULL DEFAULT '[]'::jsonb;
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS purge_after_days INTEGER NOT NULL DEFAULT 30;

    -- 2. Indexes for governance queries and background jobs
    CREATE INDEX IF NOT EXISTS idx_apps_governance ON apps(governance_state, governance_deadline);
    CREATE INDEX IF NOT EXISTS idx_apps_last_activity ON apps(last_activity_at);
    CREATE INDEX IF NOT EXISTS idx_apps_nominee ON apps(nominated_owner_user_id);
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX IF EXISTS idx_apps_nominee;
    DROP INDEX IF EXISTS idx_apps_last_activity;
    DROP INDEX IF EXISTS idx_apps_governance;

    ALTER TABLE apps DROP COLUMN IF EXISTS purge_after_days;
    ALTER TABLE apps DROP COLUMN IF EXISTS governance_warnings_sent;
    ALTER TABLE apps DROP COLUMN IF EXISTS governance_deadline;
    ALTER TABLE apps DROP COLUMN IF EXISTS governance_state;
    ALTER TABLE apps DROP COLUMN IF EXISTS inactivity_days_limit;
    ALTER TABLE apps DROP COLUMN IF EXISTS expires_at;
    ALTER TABLE apps DROP COLUMN IF EXISTS last_activity_at;
    ALTER TABLE apps DROP COLUMN IF EXISTS nominated_owner_user_id;
    """)
