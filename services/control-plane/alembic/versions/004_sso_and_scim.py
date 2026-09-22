"""SSO (OIDC & SAML) and SCIM 2.0 Directory Sync schema

Revision ID: 004_sso_and_scim
Revises: 003_kill_switch_and_revocation
Create Date: 2026-09-21 19:15:00.000000

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_sso_and_scim"
down_revision: Union[str, None] = "003_kill_switch_and_revocation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    -- 1. organization_idps
    CREATE TABLE IF NOT EXISTS organization_idps (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        provider_type VARCHAR(20) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        enforce_sso BOOLEAN NOT NULL DEFAULT FALSE,
        session_lifetime_seconds INTEGER NOT NULL DEFAULT 28800,
        oidc_issuer_url TEXT NULL,
        oidc_client_id VARCHAR(255) NULL,
        oidc_client_secret_encrypted TEXT NULL,
        oidc_discovery_url TEXT NULL,
        oidc_scopes JSONB NOT NULL DEFAULT '["openid", "email", "profile"]'::jsonb,
        saml_entity_id TEXT NULL,
        saml_sso_url TEXT NULL,
        saml_slo_url TEXT NULL,
        saml_x509_cert TEXT NULL,
        saml_sp_entity_id TEXT NULL DEFAULT 'urn:capsule:sp',
        saml_acs_url TEXT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT chk_org_idp_type CHECK (provider_type IN ('oidc', 'saml')),
        CONSTRAINT uq_org_idp_type UNIQUE (organization_id, provider_type)
    );
    CREATE INDEX IF NOT EXISTS idx_org_idps_org ON organization_idps(organization_id);

    -- 2. organization_verified_domains
    CREATE TABLE IF NOT EXISTS organization_verified_domains (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        domain VARCHAR(255) NOT NULL,
        verification_token VARCHAR(128) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        verified_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT chk_org_domain_status CHECK (status IN ('pending', 'verified', 'failed')),
        CONSTRAINT uq_verified_domain UNIQUE (domain)
    );
    CREATE INDEX IF NOT EXISTS idx_org_domains_org ON organization_verified_domains(organization_id);

    -- 3. sso_replay_cache
    CREATE TABLE IF NOT EXISTS sso_replay_cache (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        assertion_id VARCHAR(255) NOT NULL,
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_sso_replay_assertion UNIQUE (assertion_id)
    );
    CREATE INDEX IF NOT EXISTS idx_sso_replay_exp ON sso_replay_cache(expires_at);

    -- 4. organization_scim_tokens
    CREATE TABLE IF NOT EXISTS organization_scim_tokens (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        token_hash VARCHAR(128) NOT NULL,
        token_prefix VARCHAR(16) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NULL,
        CONSTRAINT chk_scim_token_status CHECK (status IN ('active', 'revoked')),
        CONSTRAINT uq_org_scim_token_hash UNIQUE (token_hash)
    );
    CREATE INDEX IF NOT EXISTS idx_scim_tokens_org ON organization_scim_tokens(organization_id);

    -- 5. scim_groups
    CREATE TABLE IF NOT EXISTS scim_groups (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        display_name VARCHAR(200) NOT NULL,
        external_id VARCHAR(255) NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_scim_group_name UNIQUE (organization_id, display_name)
    );
    CREATE INDEX IF NOT EXISTS idx_scim_groups_org ON scim_groups(organization_id);

    -- 6. scim_group_members
    CREATE TABLE IF NOT EXISTS scim_group_members (
        group_id UUID NOT NULL REFERENCES scim_groups(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (group_id, user_id)
    );
    CREATE INDEX IF NOT EXISTS idx_scim_group_members_user ON scim_group_members(user_id);

    -- 7. scim_group_role_mappings
    CREATE TABLE IF NOT EXISTS scim_group_role_mappings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        group_id UUID NOT NULL REFERENCES scim_groups(id) ON DELETE CASCADE,
        app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
        app_role VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_scim_group_role_mapping UNIQUE (group_id, app_id, app_role)
    );
    CREATE INDEX IF NOT EXISTS idx_group_role_mappings_org ON scim_group_role_mappings(organization_id);
    CREATE INDEX IF NOT EXISTS idx_group_role_mappings_group ON scim_group_role_mappings(group_id);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS scim_group_role_mappings;
    DROP TABLE IF EXISTS scim_group_members;
    DROP TABLE IF EXISTS scim_groups;
    DROP TABLE IF EXISTS organization_scim_tokens;
    DROP TABLE IF EXISTS sso_replay_cache;
    DROP TABLE IF EXISTS organization_verified_domains;
    DROP TABLE IF EXISTS organization_idps;
    """)
