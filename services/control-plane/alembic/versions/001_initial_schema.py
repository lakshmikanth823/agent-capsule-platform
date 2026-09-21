"""initial control plane schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-21 12:25:00.000000

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Extension
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    # 2. Organizations
    op.execute("""
    CREATE TABLE organizations (
        id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        slug                varchar(63) NOT NULL UNIQUE,
        name                varchar(120) NOT NULL,
        status              varchar(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended', 'deleting')),
        environment_profile jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at          timestamptz NOT NULL DEFAULT now(),
        updated_at          timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX idx_organizations_status ON organizations(status);
    """)

    # 3. Users
    op.execute("""
    CREATE TABLE users (
        id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        email               varchar(320) NOT NULL,
        display_name        varchar(200),
        identity_subject    varchar(512),
        identity_issuer     varchar(1024),
        status              varchar(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended', 'deprovisioned')),
        last_login_at       timestamptz,
        created_at          timestamptz NOT NULL DEFAULT now(),
        updated_at          timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_users_identity UNIQUE (identity_issuer, identity_subject)
    );
    CREATE UNIQUE INDEX uq_users_email_ci ON users (lower(email));
    CREATE INDEX idx_users_status ON users(status);
    """)

    # 4. Organization Members
    op.execute("""
    CREATE TABLE organization_members (
        id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id     uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        user_id             uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        platform_role       varchar(20) NOT NULL DEFAULT 'user'
                            CHECK (platform_role IN ('owner', 'editor', 'user')),
        status              varchar(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended', 'deprovisioned')),
        joined_at           timestamptz NOT NULL DEFAULT now(),
        removed_at          timestamptz,
        CONSTRAINT uq_org_member UNIQUE (organization_id, user_id)
    );
    CREATE INDEX idx_org_members_user ON organization_members(user_id);
    CREATE INDEX idx_org_members_org_role ON organization_members(organization_id, platform_role);
    """)

    # 5. Apps
    op.execute("""
    CREATE TABLE apps (
        id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id     uuid REFERENCES organizations(id) ON DELETE SET NULL,
        owner_user_id       uuid REFERENCES users(id) ON DELETE SET NULL,
        app_key             varchar(63) NOT NULL,
        name                varchar(80) NOT NULL,
        description         text,
        shape               varchar(40) NOT NULL DEFAULT 'web-app',
        runtime             varchar(40) NOT NULL DEFAULT 'node22',
        status              varchar(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('draft', 'active', 'suspended', 'archived', 'deleting')),
        current_version_id  uuid,
        published_at        timestamptz,
        archived_at         timestamptz,
        manifest            jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at          timestamptz NOT NULL DEFAULT now(),
        updated_at          timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_app_key_per_org UNIQUE (organization_id, app_key)
    );
    CREATE INDEX idx_apps_org_status ON apps(organization_id, status);
    CREATE INDEX idx_apps_owner ON apps(owner_user_id);
    CREATE INDEX idx_apps_updated ON apps(updated_at DESC);
    """)

    # 6. App Shares & Policies
    op.execute("""
    CREATE TABLE app_shares (
        id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        app_id              uuid NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
        user_id             uuid REFERENCES users(id) ON DELETE CASCADE,
        app_role            varchar(64),
        status              varchar(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'revoked', 'expired')),
        granted_by_user_id  uuid REFERENCES users(id) ON DELETE SET NULL,
        granted_at          timestamptz NOT NULL DEFAULT now(),
        expires_at          timestamptz,
        metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
        CONSTRAINT chk_app_share_expiry CHECK (expires_at IS NULL OR expires_at > granted_at),
        CONSTRAINT uq_app_user_share UNIQUE (app_id, user_id, app_role)
    );
    CREATE INDEX idx_app_shares_app_status ON app_shares(app_id, status);
    CREATE INDEX idx_app_shares_user ON app_shares(user_id);
    CREATE INDEX idx_app_shares_expiry ON app_shares(expires_at) WHERE expires_at IS NOT NULL;

    CREATE TABLE app_share_policies (
        app_id              uuid PRIMARY KEY REFERENCES apps(id) ON DELETE CASCADE,
        default_scope       varchar(20) NOT NULL DEFAULT 'org'
                            CHECK (default_scope IN ('org')),
        external_users_allowed boolean NOT NULL DEFAULT false,
        updated_by_user_id  uuid REFERENCES users(id) ON DELETE SET NULL,
        updated_at          timestamptz NOT NULL DEFAULT now()
    );
    """)

    # 7. App Versions
    op.execute("""
    CREATE TABLE app_versions (
        id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        app_id              uuid NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
        version_number      integer NOT NULL,
        status              varchar(20) NOT NULL DEFAULT 'published'
                            CHECK (status IN ('building', 'validated', 'published', 'failed', 'rolled_back')),
        source_artifact_ref text NOT NULL,
        build_artifact_ref  text,
        manifest            jsonb NOT NULL,
        db_snapshot_ref     text NOT NULL,
        publisher_user_id   uuid REFERENCES users(id) ON DELETE SET NULL,
        publisher_agent     varchar(200),
        change_description  text,
        published_at        timestamptz,
        created_at          timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_app_version UNIQUE (app_id, version_number),
        CONSTRAINT chk_published_has_timestamp CHECK (
            status NOT IN ('published', 'rolled_back') OR published_at IS NOT NULL
        )
    );
    CREATE INDEX idx_app_versions_app ON app_versions(app_id, version_number DESC);
    CREATE INDEX idx_app_versions_status ON app_versions(status);

    ALTER TABLE apps
        ADD CONSTRAINT fk_apps_current_version
        FOREIGN KEY (current_version_id)
        REFERENCES app_versions(id)
        ON DELETE SET NULL;
    """)

    # 8. Audit Events
    op.execute("""
    CREATE TABLE audit_events (
        id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id     uuid REFERENCES organizations(id) ON DELETE SET NULL,
        app_id              uuid REFERENCES apps(id) ON DELETE SET NULL,
        actor_user_id       uuid REFERENCES users(id) ON DELETE SET NULL,
        actor_agent         varchar(200),
        actor_tool          varchar(200),
        action              varchar(100) NOT NULL,
        outcome             varchar(20) NOT NULL DEFAULT 'success'
                            CHECK (outcome IN ('success', 'denied', 'failed')),
        target_type         varchar(60),
        target_id           uuid,
        ip_address          inet,
        user_agent          text,
        metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
        occurred_at         timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX idx_audit_org_time ON audit_events(organization_id, occurred_at DESC);
    CREATE INDEX idx_audit_app_time ON audit_events(app_id, occurred_at DESC);
    CREATE INDEX idx_audit_actor_time ON audit_events(actor_user_id, occurred_at DESC);
    CREATE INDEX idx_audit_action_time ON audit_events(action, occurred_at DESC);
    CREATE INDEX idx_audit_target ON audit_events(target_type, target_id);
    """)

    # 9. Capability Approvals
    op.execute("""
    CREATE TABLE capability_approvals (
        id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        app_id              uuid NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
        requested_version_id uuid REFERENCES app_versions(id) ON DELETE SET NULL,
        capability_key      varchar(200) NOT NULL,
        previous_value      jsonb,
        requested_value     jsonb,
        status              varchar(20) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
        requested_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
        approved_by_user_id  uuid REFERENCES users(id) ON DELETE SET NULL,
        requested_at        timestamptz NOT NULL DEFAULT now(),
        decided_at          timestamptz,
        CONSTRAINT chk_capability_decision_actor CHECK (
            status IN ('pending', 'expired') OR approved_by_user_id IS NOT NULL
        )
    );
    CREATE INDEX idx_capability_approvals_app ON capability_approvals(app_id, status);
    """)

    # 10. Triggers & Helpers
    op.execute("""
    CREATE OR REPLACE FUNCTION set_updated_at()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$;

    CREATE TRIGGER trg_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TRIGGER trg_apps_updated_at
    BEFORE UPDATE ON apps
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TRIGGER trg_app_share_policies_updated_at
    BEFORE UPDATE ON app_share_policies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    # 1. Drop Triggers & Function
    op.execute("""
    DROP TRIGGER IF EXISTS trg_app_share_policies_updated_at ON app_share_policies;
    DROP TRIGGER IF EXISTS trg_apps_updated_at ON apps;
    DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
    DROP TRIGGER IF EXISTS trg_organizations_updated_at ON organizations;
    DROP FUNCTION IF EXISTS set_updated_at();
    """)

    # 2. Drop Foreign Key on Apps
    op.execute("ALTER TABLE apps DROP CONSTRAINT IF EXISTS fk_apps_current_version;")

    # 3. Drop Tables in reverse dependency order
    op.execute("DROP TABLE IF EXISTS capability_approvals CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS app_versions CASCADE;")
    op.execute("DROP TABLE IF EXISTS app_share_policies CASCADE;")
    op.execute("DROP TABLE IF EXISTS app_shares CASCADE;")
    op.execute("DROP TABLE IF EXISTS apps CASCADE;")
    op.execute("DROP TABLE IF EXISTS organization_members CASCADE;")
    op.execute("DROP TABLE IF EXISTS users CASCADE;")
    op.execute("DROP TABLE IF EXISTS organizations CASCADE;")
