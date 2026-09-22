"""
SQLAlchemy 2.0 Typed Models for Software Capsule Control-Plane Database
Directly matching docs/backend-database-schema/backend_schema.sql
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import (
    String, Text, Boolean, Integer, BigInteger, Float, Numeric, DateTime, ForeignKey,
    CheckConstraint, UniqueConstraint, Index, func, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    environment_profile: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    audit_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="90"
    )
    tokens_revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sessions_revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    suspension_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    members: Mapped[List[OrganizationMember]] = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    apps: Mapped[List[App]] = relationship("App", back_populates="organization")
    audit_checkpoints: Mapped[List[OrganizationAuditCheckpoint]] = relationship("OrganizationAuditCheckpoint", back_populates="organization", cascade="all, delete-orphan")
    audit_webhook: Mapped[Optional[OrganizationAuditWebhook]] = relationship("OrganizationAuditWebhook", back_populates="organization", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'deleting')", name="chk_organizations_status"),
        Index("idx_organizations_status", "status"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    identity_subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    identity_issuer: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    tokens_revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sessions_revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[List[OrganizationMember]] = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")
    owned_apps: Mapped[List[App]] = relationship("App", back_populates="owner", foreign_keys="[App.owner_user_id]")
    shares: Mapped[List[AppShare]] = relationship("AppShare", back_populates="user", foreign_keys="AppShare.user_id", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'deprovisioned')", name="chk_users_status"),
        UniqueConstraint("identity_issuer", "identity_subject", name="uq_users_identity"),
        Index("uq_users_email_ci", func.lower(email), unique=True),
        Index("idx_users_status", "status"),
    )


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    platform_role: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="user"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship("Organization", back_populates="members")
    user: Mapped[User] = relationship("User", back_populates="memberships")

    __table_args__ = (
        CheckConstraint("platform_role IN ('owner', 'editor', 'user')", name="chk_org_members_role"),
        CheckConstraint("status IN ('active', 'suspended', 'deprovisioned')", name="chk_org_members_status"),
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        Index("idx_org_members_user", "user_id"),
        Index("idx_org_members_org_role", "organization_id", "platform_role"),
    )


class App(Base):
    __tablename__ = "apps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    app_key: Mapped[str] = mapped_column(String(63), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shape: Mapped[str] = mapped_column(String(40), nullable=False, server_default="web-app")
    runtime: Mapped[str] = mapped_column(String(40), nullable=False, server_default="node22")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    current_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    suspension_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manifest: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    nominated_owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    inactivity_days_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    governance_state: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="normal"
    )
    governance_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    governance_warnings_sent: Mapped[List[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    purge_after_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="30"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Optional[Organization]] = relationship("Organization", back_populates="apps")
    owner: Mapped[Optional[User]] = relationship("User", back_populates="owned_apps", foreign_keys=[owner_user_id])
    nominated_owner: Mapped[Optional[User]] = relationship("User", foreign_keys=[nominated_owner_user_id])
    versions: Mapped[List[AppVersion]] = relationship(
        "AppVersion", back_populates="app", foreign_keys="AppVersion.app_id", cascade="all, delete-orphan"
    )
    shares: Mapped[List[AppShare]] = relationship("AppShare", back_populates="app", cascade="all, delete-orphan")
    share_policy: Mapped[Optional[AppSharePolicy]] = relationship("AppSharePolicy", back_populates="app", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'suspended', 'archived', 'deleting')", name="chk_apps_status"),
        UniqueConstraint("organization_id", "app_key", name="uq_app_key_per_org"),
        Index("idx_apps_org_status", "organization_id", "status"),
        Index("idx_apps_owner", "owner_user_id"),
        Index("idx_apps_updated", updated_at.desc()),
        Index("idx_apps_governance", "governance_state", "governance_deadline"),
        Index("idx_apps_last_activity", "last_activity_at"),
        Index("idx_apps_nominee", "nominated_owner_user_id"),
    )


class AppShare(Base):
    __tablename__ = "app_shares"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    app_role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    granted_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[Dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    app: Mapped[App] = relationship("App", back_populates="shares")
    user: Mapped[Optional[User]] = relationship("User", back_populates="shares", foreign_keys=[user_id])

    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked', 'expired')", name="chk_app_shares_status"),
        CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="chk_app_share_expiry"),
        UniqueConstraint("app_id", "user_id", "app_role", name="uq_app_user_share"),
        Index("idx_app_shares_app_status", "app_id", "status"),
        Index("idx_app_shares_user", "user_id"),
        Index("idx_app_shares_expiry", "expires_at", postgresql_where=text("expires_at IS NOT NULL")),
    )


class AppSharePolicy(Base):
    __tablename__ = "app_share_policies"

    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), primary_key=True
    )
    default_scope: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="org"
    )
    external_users_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    app: Mapped[App] = relationship("App", back_populates="share_policy")

    __table_args__ = (
        CheckConstraint("default_scope IN ('org')", name="chk_app_share_policies_scope"),
    )


class AppVersion(Base):
    __tablename__ = "app_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="published"
    )
    source_artifact_ref: Mapped[str] = mapped_column(Text, nullable=False)
    build_artifact_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manifest: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    db_snapshot_ref: Mapped[str] = mapped_column(Text, nullable=False)
    publisher_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    publisher_agent: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    change_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    app: Mapped[App] = relationship("App", back_populates="versions", foreign_keys=[app_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ('building', 'validated', 'published', 'failed', 'rolled_back')",
            name="chk_app_versions_status",
        ),
        CheckConstraint(
            "status NOT IN ('published', 'rolled_back') OR published_at IS NOT NULL",
            name="chk_published_has_timestamp",
        ),
        UniqueConstraint("app_id", "version_number", name="uq_app_version"),
        Index("idx_app_versions_app", "app_id", version_number.desc()),
        Index("idx_app_versions_status", "status"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    app_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_agent: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    actor_tool: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="success"
    )
    target_type: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[Dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    prev_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="0000000000000000000000000000000000000000000000000000000000000000"
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("outcome IN ('success', 'denied', 'failed')", name="chk_audit_events_outcome"),
        Index("idx_audit_org_time", "organization_id", occurred_at.desc()),
        Index("idx_audit_app_time", "app_id", occurred_at.desc()),
        Index("idx_audit_actor_time", "actor_user_id", occurred_at.desc()),
        Index("idx_audit_action_time", "action", occurred_at.desc()),
        Index("idx_audit_target", "target_type", "target_id"),
        Index("idx_audit_org_seq", "organization_id", "sequence_number"),
    )


class CapabilityApproval(Base):
    __tablename__ = "capability_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False
    )
    requested_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_versions.id", ondelete="SET NULL"), nullable=True
    )
    capability_key: Mapped[str] = mapped_column(String(200), nullable=False)
    previous_value: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    requested_value: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    requested_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'expired')", name="chk_capability_approvals_status"),
        CheckConstraint(
            "status IN ('pending', 'expired') OR approved_by_user_id IS NOT NULL",
            name="chk_capability_decision_actor",
        ),
        Index("idx_capability_approvals_app", "app_id", "status"),
    )


class ConnectorCredential(Base):
    __tablename__ = "connector_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    app_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=True
    )
    connector_name: Mapped[str] = mapped_column(String(100), nullable=False)
    identity_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="service"
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    encrypted_data: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[str] = mapped_column(String(50), nullable=False, server_default="v1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("identity_type IN ('service', 'viewer')", name="chk_connector_cred_identity"),
        UniqueConstraint("organization_id", "connector_name", "identity_type", "user_id", name="uq_connector_cred"),
        Index("idx_connector_cred_lookup", "organization_id", "connector_name", "identity_type"),
        Index("idx_connector_cred_app", "app_id", postgresql_where=text("app_id IS NOT NULL")),
    )


class OrganizationIdentityProvider(Base):
    __tablename__ = "organization_idps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enforce_sso: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    session_lifetime_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=28800)
    oidc_issuer_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oidc_client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    oidc_client_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oidc_discovery_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oidc_scopes: Mapped[List[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[\"openid\", \"email\", \"profile\"]'::jsonb"))
    saml_entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    saml_sso_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    saml_slo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    saml_x509_cert: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    saml_sp_entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, server_default="urn:capsule:sp")
    saml_acs_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship("Organization")

    __table_args__ = (
        CheckConstraint("provider_type IN ('oidc', 'saml')", name="chk_org_idp_type"),
        UniqueConstraint("organization_id", "provider_type", name="uq_org_idp_type"),
        Index("idx_org_idps_org", "organization_id"),
    )


class OrganizationVerifiedDomain(Base):
    __tablename__ = "organization_verified_domains"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    verification_token: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship("Organization")

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'verified', 'failed')", name="chk_org_domain_status"),
        Index("idx_org_domains_org", "organization_id"),
    )


class SSOReplayCache(Base):
    __tablename__ = "sso_replay_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    assertion_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_sso_replay_exp", "expires_at"),
    )


class OrganizationSCIMToken(Base):
    __tablename__ = "organization_scim_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship("Organization")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked')", name="chk_scim_token_status"),
        Index("idx_scim_tokens_org", "organization_id"),
    )


class SCIMGroup(Base):
    __tablename__ = "scim_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship("Organization")
    members: Mapped[List[SCIMGroupMember]] = relationship("SCIMGroupMember", back_populates="group", cascade="all, delete-orphan")
    role_mappings: Mapped[List[SCIMGroupRoleMapping]] = relationship("SCIMGroupRoleMapping", back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "display_name", name="uq_scim_group_name"),
        Index("idx_scim_groups_org", "organization_id"),
    )


class SCIMGroupMember(Base):
    __tablename__ = "scim_group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scim_groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    group: Mapped[SCIMGroup] = relationship("SCIMGroup", back_populates="members")
    user: Mapped[User] = relationship("User")

    __table_args__ = (
        Index("idx_scim_group_members_user", "user_id"),
    )


class SCIMGroupRoleMapping(Base):
    __tablename__ = "scim_group_role_mappings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scim_groups.id", ondelete="CASCADE"), nullable=False
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False
    )
    app_role: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    group: Mapped[SCIMGroup] = relationship("SCIMGroup", back_populates="role_mappings")
    app: Mapped[App] = relationship("App")

    __table_args__ = (
        UniqueConstraint("group_id", "app_id", "app_role", name="uq_scim_group_role_mapping"),
        Index("idx_group_role_mappings_org", "organization_id"),
        Index("idx_group_role_mappings_group", "group_id"),
    )


class OrganizationAuditCheckpoint(Base):
    __tablename__ = "organization_audit_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    checkpoint_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checkpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    purged_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="audit_checkpoints")

    __table_args__ = (
        Index("idx_audit_checkpoints_org", "organization_id"),
    )


class OrganizationAuditWebhook(Base):
    __tablename__ = "organization_audit_webhooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    secret_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="audit_webhook")

    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_org_audit_webhook"),
        Index("idx_audit_webhooks_org", "organization_id"),
    )


class AIUsageRecord(Base):
    __tablename__ = "ai_usage_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="success")
    prompt_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped[Organization] = relationship("Organization")
    app: Mapped[App] = relationship("App")
    user: Mapped[Optional[User]] = relationship("User")

    __table_args__ = (
        Index("idx_ai_usage_org_created", "organization_id", "created_at"),
        Index("idx_ai_usage_app_created", "app_id", "created_at"),
        Index("idx_ai_usage_user_created", "user_id", "created_at"),
        Index("idx_ai_usage_app_model", "app_id", "model"),
    )


