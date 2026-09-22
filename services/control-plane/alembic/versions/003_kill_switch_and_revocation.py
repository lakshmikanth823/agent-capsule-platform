"""kill switch and revocation columns

Revision ID: 003_kill_switch_and_revocation
Revises: 002_connector_credentials
Create Date: 2026-09-21 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_kill_switch_and_revocation"
down_revision: Union[str, None] = "002_connector_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    -- Organizations suspension and revocation columns
    ALTER TABLE organizations ADD COLUMN IF NOT EXISTS tokens_revoked_at timestamptz NULL;
    ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sessions_revoked_at timestamptz NULL;
    ALTER TABLE organizations ADD COLUMN IF NOT EXISTS suspended_at timestamptz NULL;
    ALTER TABLE organizations ADD COLUMN IF NOT EXISTS suspended_by_user_id uuid NULL REFERENCES users(id) ON DELETE SET NULL;
    ALTER TABLE organizations ADD COLUMN IF NOT EXISTS suspension_reason text NULL;

    -- Users revocation columns
    ALTER TABLE users ADD COLUMN IF NOT EXISTS tokens_revoked_at timestamptz NULL;
    ALTER TABLE users ADD COLUMN IF NOT EXISTS sessions_revoked_at timestamptz NULL;

    -- Apps suspension columns
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS suspended_at timestamptz NULL;
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS suspended_by_user_id uuid NULL REFERENCES users(id) ON DELETE SET NULL;
    ALTER TABLE apps ADD COLUMN IF NOT EXISTS suspension_reason text NULL;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE apps DROP COLUMN IF EXISTS suspension_reason;
    ALTER TABLE apps DROP COLUMN IF EXISTS suspended_by_user_id;
    ALTER TABLE apps DROP COLUMN IF EXISTS suspended_at;

    ALTER TABLE users DROP COLUMN IF EXISTS sessions_revoked_at;
    ALTER TABLE users DROP COLUMN IF EXISTS tokens_revoked_at;

    ALTER TABLE organizations DROP COLUMN IF EXISTS suspension_reason;
    ALTER TABLE organizations DROP COLUMN IF EXISTS suspended_by_user_id;
    ALTER TABLE organizations DROP COLUMN IF EXISTS suspended_at;
    ALTER TABLE organizations DROP COLUMN IF EXISTS sessions_revoked_at;
    ALTER TABLE organizations DROP COLUMN IF EXISTS tokens_revoked_at;
    """)
