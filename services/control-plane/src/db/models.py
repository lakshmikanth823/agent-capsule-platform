"""
SQLAlchemy 2.0 Typed Models for Software Capsule Control-Plane Database
Directly matching docs/backend-database-schema/backend_schema.sql
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import (
    String, Text, Boolean, Integer, DateTime, ForeignKey,
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    members: Mapped[List[OrganizationMember]] = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    apps: Mapped[List[App]] = relationship("App", back_populates="organization")

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
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[List[OrganizationMember]] = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")
    owned_apps: Mapped[List[App]] = relationship("App", back_populates="owner")
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
    manifest: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Optional[Organization]] = relationship("Organization", back_populates="apps")
    owner: Mapped[Optional[User]] = relationship("User", back_populates="owned_apps")
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
