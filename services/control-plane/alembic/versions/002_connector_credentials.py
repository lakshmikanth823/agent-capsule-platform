"""connector credentials table

Revision ID: 002_connector_credentials
Revises: 001_initial_schema
Create Date: 2026-09-21 16:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_connector_credentials"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE connector_credentials (
        id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id     uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        app_id              uuid REFERENCES apps(id) ON DELETE CASCADE,
        connector_name      varchar(100) NOT NULL,
        identity_type       varchar(20) NOT NULL DEFAULT 'service'
                            CHECK (identity_type IN ('service', 'viewer')),
        user_id             uuid REFERENCES users(id) ON DELETE CASCADE,
        encrypted_data      text NOT NULL,
        key_id              varchar(50) NOT NULL DEFAULT 'v1',
        created_at          timestamptz NOT NULL DEFAULT now(),
        updated_at          timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_connector_cred UNIQUE (organization_id, connector_name, identity_type, user_id)
    );
    CREATE INDEX idx_connector_cred_lookup ON connector_credentials(organization_id, connector_name, identity_type);
    CREATE INDEX idx_connector_cred_app ON connector_credentials(app_id) WHERE app_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS connector_credentials CASCADE;")
