"""AI Gateway usage metering, budgets, and logging

Revision ID: 007_ai_gateway
Revises: 006_governance_and_inventory
Create Date: 2026-09-22 11:15:00.000000

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_ai_gateway"
down_revision: Union[str, None] = "006_governance_and_inventory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    -- 1. Create ai_usage_records table for token & cost metering
    CREATE TABLE IF NOT EXISTS ai_usage_records (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
        user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        model VARCHAR(80) NOT NULL,
        provider VARCHAR(40) NOT NULL,
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        total_tokens INTEGER NOT NULL DEFAULT 0,
        estimated_cost_usd NUMERIC(12, 6) NOT NULL DEFAULT 0.0,
        duration_ms INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(30) NOT NULL DEFAULT 'success',
        prompt_content TEXT NULL,
        response_content TEXT NULL,
        redacted BOOLEAN NOT NULL DEFAULT FALSE,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- 2. Performance indexes for budget tracking and usage reporting
    CREATE INDEX IF NOT EXISTS idx_ai_usage_org_created ON ai_usage_records(organization_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_ai_usage_app_created ON ai_usage_records(app_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_ai_usage_user_created ON ai_usage_records(user_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_ai_usage_app_model ON ai_usage_records(app_id, model);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS ai_usage_records;
    """)
