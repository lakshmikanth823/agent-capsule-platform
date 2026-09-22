"""Audit hash chain, retention checkpoints, webhooks, and append-only trigger

Revision ID: 005_audit_hash_chain
Revises: 004_sso_and_scim
Create Date: 2026-09-22 10:25:00.000000

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_audit_hash_chain"
down_revision: Union[str, None] = "004_sso_and_scim"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    -- 1. Add audit_retention_days to organizations
    ALTER TABLE organizations ADD COLUMN IF NOT EXISTS audit_retention_days INTEGER NOT NULL DEFAULT 90;

    -- 2. Add hash chain columns to audit_events
    ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS sequence_number BIGINT NOT NULL DEFAULT 1;
    ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64) NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000';
    ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS event_hash VARCHAR(64) NOT NULL DEFAULT '';

    CREATE INDEX IF NOT EXISTS idx_audit_org_seq ON audit_events(organization_id, sequence_number);

    -- 3. organization_audit_checkpoints (preserves hash chain validity across retention purges)
    CREATE TABLE IF NOT EXISTS organization_audit_checkpoints (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        checkpoint_sequence BIGINT NOT NULL,
        checkpoint_hash VARCHAR(64) NOT NULL,
        purged_count INTEGER NOT NULL DEFAULT 0,
        purged_before TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_audit_checkpoints_org ON organization_audit_checkpoints(organization_id);

    -- 4. organization_audit_webhooks (streaming log destinations like Datadog, Splunk, SIEM)
    CREATE TABLE IF NOT EXISTS organization_audit_webhooks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        url VARCHAR(1024) NOT NULL,
        secret_token_encrypted TEXT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_org_audit_webhook UNIQUE (organization_id)
    );
    CREATE INDEX IF NOT EXISTS idx_audit_webhooks_org ON organization_audit_webhooks(organization_id);

    -- 5. Immutability trigger: prevent direct UPDATE and unauthorized DELETE on audit_events
    CREATE OR REPLACE FUNCTION trg_prevent_audit_mutation()
    RETURNS TRIGGER AS $$
    BEGIN
        IF current_setting('capsule.allow_retention_purge', true) = 'on' THEN
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            ELSE
                RETURN NEW;
            END IF;
        END IF;

        IF TG_OP = 'UPDATE' THEN
            IF OLD.id = NEW.id 
               AND OLD.sequence_number = NEW.sequence_number 
               AND OLD.event_hash = NEW.event_hash 
               AND OLD.action = NEW.action 
               AND OLD.occurred_at = NEW.occurred_at 
               AND OLD.metadata = NEW.metadata THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'audit_events is append-only: UPDATE operations are strictly prohibited.';
        ELSIF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'audit_events is append-only: DELETE operations are strictly prohibited except via retention maintenance.';
        END IF;
        RETURN OLD;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_audit_events_immutable ON audit_events;
    CREATE TRIGGER trg_audit_events_immutable
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION trg_prevent_audit_mutation();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS trg_audit_events_immutable ON audit_events;
    DROP FUNCTION IF EXISTS trg_prevent_audit_mutation();

    DROP TABLE IF EXISTS organization_audit_webhooks CASCADE;
    DROP TABLE IF EXISTS organization_audit_checkpoints CASCADE;

    DROP INDEX IF EXISTS idx_audit_org_seq;
    ALTER TABLE audit_events DROP COLUMN IF EXISTS event_hash;
    ALTER TABLE audit_events DROP COLUMN IF EXISTS prev_hash;
    ALTER TABLE audit_events DROP COLUMN IF EXISTS sequence_number;

    ALTER TABLE organizations DROP COLUMN IF EXISTS audit_retention_days;
    """)
