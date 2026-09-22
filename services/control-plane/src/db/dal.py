"""
Typed Data Access Layer (DAL) for Software Capsule Platform Control Plane
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import select, update, delete, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

import hashlib
import secrets

from .models import (
    Organization, User, OrganizationMember, App,
    AppShare, AppSharePolicy, AppVersion, AuditEvent, CapabilityApproval,
    ConnectorCredential, OrganizationIdentityProvider, OrganizationVerifiedDomain,
    SSOReplayCache, OrganizationSCIMToken, SCIMGroup, SCIMGroupMember,
    SCIMGroupRoleMapping, OrganizationAuditCheckpoint, OrganizationAuditWebhook,
    AIUsageRecord
)
from crypto import encrypt_secret, decrypt_secret
from services.audit_verifier import (
    compute_audit_event_hash,
    redact_audit_metadata,
    format_audit_timestamp,
    GENESIS_HASH,
)
from services.audit_webhook import dispatch_audit_webhook



class OrganizationDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        slug: str,
        name: str,
        status: str = "active",
        environment_profile: Optional[Dict[str, Any]] = None,
    ) -> Organization:
        org = Organization(
            slug=slug,
            name=name,
            status=status,
            environment_profile=environment_profile or {},
        )
        self.session.add(org)
        await self.session.flush()
        return org

    async def get_by_id(self, org_id: uuid.UUID) -> Optional[Organization]:
        result = await self.session.execute(select(Organization).where(Organization.id == org_id))
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Optional[Organization]:
        result = await self.session.execute(select(Organization).where(Organization.slug == slug))
        return result.scalar_one_or_none()

    async def list_all(self) -> List[Organization]:
        result = await self.session.execute(select(Organization).order_by(Organization.name))
        return list(result.scalars().all())

    async def suspend(
        self, org_id: uuid.UUID, user_id: Optional[uuid.UUID], reason: str
    ) -> Optional[Organization]:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(
                status="suspended",
                suspended_at=now,
                suspended_by_user_id=user_id,
                suspension_reason=reason,
                updated_at=now,
            )
        )
        return await self.get_by_id(org_id)

    async def resume(
        self, org_id: uuid.UUID, user_id: Optional[uuid.UUID] = None
    ) -> Optional[Organization]:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(
                status="active",
                suspended_at=None,
                suspended_by_user_id=None,
                suspension_reason=None,
                updated_at=now,
            )
        )
        return await self.get_by_id(org_id)

    async def revoke_tokens(self, org_id: uuid.UUID) -> datetime:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(tokens_revoked_at=now, updated_at=now)
        )
        return now

    async def revoke_sessions(self, org_id: uuid.UUID) -> datetime:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(sessions_revoked_at=now, updated_at=now)
        )
        return now

    async def disable_connector(
        self, org_id: uuid.UUID, connector_name: str, reason: Optional[str] = None
    ) -> Organization:
        org = await self.get_by_id(org_id)
        if not org:
            raise ValueError(f"Organization {org_id} not found.")
        profile = dict(org.environment_profile or {})
        disabled = list(profile.get("disabled_connectors", []))
        if connector_name not in disabled:
            disabled.append(connector_name)
        profile["disabled_connectors"] = disabled
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(environment_profile=profile, updated_at=now)
        )
        await self.session.flush()
        return await self.get_by_id(org_id)  # type: ignore

    async def update_environment_profile(
        self, org_id: uuid.UUID, profile: Dict[str, Any]
    ) -> Optional[Organization]:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(environment_profile=profile, updated_at=now)
        )
        await self.session.flush()
        return await self.get_by_id(org_id)


class UserDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        email: str,
        display_name: Optional[str] = None,
        identity_subject: Optional[str] = None,
        identity_issuer: Optional[str] = None,
        status: str = "active",
    ) -> User:
        user = User(
            email=email,
            display_name=display_name,
            identity_subject=identity_subject,
            identity_issuer=identity_issuer,
            status=status,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(func.lower(User.email) == email.lower())
        )
        return result.scalar_one_or_none()

    async def get_by_identity(
        self, identity_issuer: str, identity_subject: str
    ) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(
                and_(
                    User.identity_issuer == identity_issuer,
                    User.identity_subject == identity_subject,
                )
            )
        )
        return result.scalar_one_or_none()

    async def add_to_org(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        platform_role: str = "user",
        status: str = "active",
    ) -> OrganizationMember:
        member = OrganizationMember(
            organization_id=organization_id,
            user_id=user_id,
            platform_role=platform_role,
            status=status,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def get_org_members(self, organization_id: uuid.UUID) -> List[OrganizationMember]:
        result = await self.session.execute(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .order_by(OrganizationMember.joined_at)
        )
        return list(result.scalars().all())

    async def revoke_tokens(self, user_id: uuid.UUID) -> datetime:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(tokens_revoked_at=now, updated_at=now)
        )
        return now

    async def revoke_sessions(self, user_id: uuid.UUID) -> datetime:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(sessions_revoked_at=now, updated_at=now)
        )
        return now

    async def set_status(self, user_id: uuid.UUID, status: str) -> Optional[User]:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(status=status, updated_at=now)
        )
        return await self.get_by_id(user_id)

    async def update_user(
        self,
        user_id: uuid.UUID,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Optional[User]:
        now = datetime.now(timezone.utc)
        values: Dict[str, Any] = {"updated_at": now}
        if display_name is not None:
            values["display_name"] = display_name
        if email is not None:
            values["email"] = email
        await self.session.execute(
            update(User).where(User.id == user_id).values(**values)
        )
        return await self.get_by_id(user_id)

    async def list_users_for_org(
        self, organization_id: uuid.UUID, email_filter: Optional[str] = None
    ) -> List[User]:
        query = (
            select(User)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == organization_id)
        )
        if email_filter:
            query = query.where(func.lower(User.email) == email_filter.lower())
        result = await self.session.execute(query.order_by(User.email.asc()))
        return list(result.scalars().all())

    async def update_org_member_status(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, status: str
    ) -> None:
        await self.session.execute(
            update(OrganizationMember)
            .where(
                and_(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.user_id == user_id,
                )
            )
            .values(status=status)
        )


class AppDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        app_key: str,
        name: str,
        organization_id: Optional[uuid.UUID] = None,
        owner_user_id: Optional[uuid.UUID] = None,
        description: Optional[str] = None,
        shape: str = "web-app",
        runtime: str = "node22",
        status: str = "active",
        manifest: Optional[Dict[str, Any]] = None,
    ) -> App:
        app = App(
            app_key=app_key,
            name=name,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            description=description,
            shape=shape,
            runtime=runtime,
            status=status,
            manifest=manifest or {},
        )
        self.session.add(app)
        await self.session.flush()
        return app

    async def get_by_id(self, app_id: uuid.UUID) -> Optional[App]:
        result = await self.session.execute(select(App).where(App.id == app_id))
        return result.scalar_one_or_none()

    async def get_by_key(
        self, organization_id: Optional[uuid.UUID], app_key: str
    ) -> Optional[App]:
        query = select(App).where(App.app_key == app_key)
        if organization_id is not None:
            query = query.where(App.organization_id == organization_id)
        else:
            query = query.where(App.organization_id.is_(None))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_org(self, organization_id: uuid.UUID) -> List[App]:
        result = await self.session.execute(
            select(App).where(App.organization_id == organization_id).order_by(App.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id_or_key(
        self, organization_id: uuid.UUID, app_id_or_key: str
    ) -> Optional[App]:
        try:
            val_uuid = uuid.UUID(app_id_or_key)
            app = await self.get_by_id(val_uuid)
            if app and app.organization_id == organization_id:
                return app
        except ValueError:
            pass
        return await self.get_by_key(organization_id, app_id_or_key)

    async def set_current_version(
        self,
        app_id: uuid.UUID,
        version_id: uuid.UUID,
        published_at: Optional[datetime] = None,
        manifest: Optional[Dict[str, Any]] = None,
        status: Optional[str] = "active",
    ):
        values: Dict[str, Any] = {
            "current_version_id": version_id,
            "published_at": published_at or func.now(),
        }
        if manifest is not None:
            values["manifest"] = manifest
        if status is not None:
            values["status"] = status

        await self.session.execute(
            update(App)
            .where(App.id == app_id)
            .values(**values)
        )

    async def suspend(
        self, app_id: uuid.UUID, user_id: Optional[uuid.UUID], reason: str
    ) -> Optional[App]:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(App)
            .where(App.id == app_id)
            .values(
                status="suspended",
                suspended_at=now,
                suspended_by_user_id=user_id,
                suspension_reason=reason,
                updated_at=now,
            )
        )
        return await self.get_by_id(app_id)

    async def resume(
        self, app_id: uuid.UUID, user_id: Optional[uuid.UUID] = None
    ) -> Optional[App]:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(App)
            .where(App.id == app_id)
            .values(
                status="active",
                suspended_at=None,
                suspended_by_user_id=None,
                suspension_reason=None,
                updated_at=now,
            )
        )
        return await self.get_by_id(app_id)

    async def suspend_all_for_org(
        self, organization_id: uuid.UUID, user_id: Optional[uuid.UUID], reason: str
    ) -> List[App]:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(App)
            .where(and_(App.organization_id == organization_id, App.status == "active"))
            .values(
                status="suspended",
                suspended_at=now,
                suspended_by_user_id=user_id,
                suspension_reason=reason,
                updated_at=now,
            )
        )
        return await self.list_by_org(organization_id)

    async def count_active_apps_for_user(
        self, user_id: uuid.UUID, organization_id: Optional[uuid.UUID] = None
    ) -> int:
        conditions = [App.owner_user_id == user_id, App.status.in_(("active", "suspended", "draft"))]
        if organization_id:
            conditions.append(App.organization_id == organization_id)
        result = await self.session.execute(
            select(func.count(App.id)).where(and_(*conditions))
        )
        return result.scalar() or 0

    async def update_compliance_metadata(
        self,
        app_id: uuid.UUID,
        compliance_info: Dict[str, Any],
        status: Optional[str] = None,
        suspension_reason: Optional[str] = None,
    ) -> Optional[App]:
        now = datetime.now(timezone.utc)
        app = await self.get_by_id(app_id)
        if not app:
            return None
        updated_manifest = dict(app.manifest or {})
        updated_manifest["_compliance"] = compliance_info
        values: Dict[str, Any] = {
            "manifest": updated_manifest,
            "updated_at": now,
        }
        if status:
            values["status"] = status
            if status == "suspended":
                values["suspended_at"] = now
                values["suspension_reason"] = suspension_reason
        await self.session.execute(
            update(App).where(App.id == app_id).values(**values)
        )
        await self.session.flush()
        return await self.get_by_id(app_id)

    async def transfer_ownership(
        self,
        app_id: uuid.UUID,
        new_owner_id: uuid.UUID,
        clear_governance_pending: bool = True,
    ) -> Optional[App]:
        now = datetime.now(timezone.utc)
        app = await self.get_by_id(app_id)
        if not app:
            return None
        app.owner_user_id = new_owner_id
        if clear_governance_pending and app.governance_state in ("pending_owner", "grace_period_expired"):
            app.governance_state = "normal"
            app.governance_deadline = None
            if app.status == "suspended" and app.suspension_reason and "grace period" in app.suspension_reason.lower():
                app.status = "active"
                app.suspended_at = None
                app.suspension_reason = None
        app.updated_at = now
        await self.session.flush()
        return app

    async def set_governance_settings(
        self,
        app_id: uuid.UUID,
        nominated_owner_id: Any = ...,
        expires_at: Any = ...,
        inactivity_days_limit: Any = ...,
        purge_after_days: Any = ...,
    ) -> Optional[App]:
        app = await self.get_by_id(app_id)
        if not app:
            return None
        now = datetime.now(timezone.utc)
        if nominated_owner_id is not ...:
            app.nominated_owner_user_id = nominated_owner_id
        if expires_at is not ...:
            app.expires_at = expires_at
        if inactivity_days_limit is not ...:
            app.inactivity_days_limit = inactivity_days_limit
        if purge_after_days is not ...:
            app.purge_after_days = purge_after_days
        app.updated_at = now
        await self.session.flush()
        return app

    async def record_activity(
        self, app_id: uuid.UUID, timestamp: Optional[datetime] = None
    ) -> None:
        now = timestamp or datetime.now(timezone.utc)
        await self.session.execute(
            update(App)
            .where(App.id == app_id)
            .values(last_activity_at=now, updated_at=now)
        )
        await self.session.flush()

    async def update_governance_state(
        self,
        app_id: uuid.UUID,
        state: str,
        deadline: Optional[datetime] = None,
        warnings_sent: Optional[List[Any]] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        values: Dict[str, Any] = {"governance_state": state, "updated_at": now}
        if deadline is not None:
            values["governance_deadline"] = deadline
        if warnings_sent is not None:
            values["governance_warnings_sent"] = warnings_sent
        await self.session.execute(
            update(App).where(App.id == app_id).values(**values)
        )
        await self.session.flush()

    async def archive_app(
        self,
        app_id: uuid.UUID,
        current_time: Optional[datetime] = None,
        deadline: Optional[datetime] = None,
    ) -> Optional[App]:
        now = current_time or datetime.now(timezone.utc)
        app = await self.get_by_id(app_id)
        if not app:
            return None
        app.status = "archived"
        app.governance_state = "archived"
        app.archived_at = now
        app.governance_deadline = deadline
        app.updated_at = now
        await self.session.flush()
        return app


class AppVersionDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        app_id: uuid.UUID,
        version_number: int,
        source_artifact_ref: str,
        manifest: Dict[str, Any],
        db_snapshot_ref: str,
        build_artifact_ref: Optional[str] = None,
        publisher_user_id: Optional[uuid.UUID] = None,
        publisher_agent: Optional[str] = None,
        change_description: Optional[str] = None,
        status: str = "published",
        published_at: Optional[datetime] = None,
    ) -> AppVersion:
        if status in ("published", "rolled_back") and published_at is None:
            published_at = datetime.utcnow()

        version = AppVersion(
            app_id=app_id,
            version_number=version_number,
            status=status,
            source_artifact_ref=source_artifact_ref,
            build_artifact_ref=build_artifact_ref,
            manifest=manifest,
            db_snapshot_ref=db_snapshot_ref,
            publisher_user_id=publisher_user_id,
            publisher_agent=publisher_agent,
            change_description=change_description,
            published_at=published_at,
        )
        self.session.add(version)
        await self.session.flush()
        return version

    async def get_by_id(self, version_id: uuid.UUID) -> Optional[AppVersion]:
        result = await self.session.execute(
            select(AppVersion).where(AppVersion.id == version_id)
        )
        return result.scalar_one_or_none()

    async def get_by_number(self, app_id: uuid.UUID, version_number: int) -> Optional[AppVersion]:
        result = await self.session.execute(
            select(AppVersion).where(
                and_(
                    AppVersion.app_id == app_id,
                    AppVersion.version_number == version_number,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_for_app(self, app_id: uuid.UUID) -> List[AppVersion]:
        result = await self.session.execute(
            select(AppVersion)
            .where(AppVersion.app_id == app_id)
            .order_by(AppVersion.version_number.desc())
        )
        return list(result.scalars().all())

    async def set_status(self, version_id: uuid.UUID, status: str) -> Optional[AppVersion]:
        version = await self.get_by_id(version_id)
        if version:
            version.status = status
            await self.session.flush()
        return version


class AppShareDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_share(
        self,
        app_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        app_role: Optional[str] = None,
        status: str = "active",
        granted_by_user_id: Optional[uuid.UUID] = None,
        expires_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AppShare:
        share = AppShare(
            app_id=app_id,
            user_id=user_id,
            app_role=app_role,
            status=status,
            granted_by_user_id=granted_by_user_id,
            expires_at=expires_at,
            metadata_=metadata or {},
        )
        self.session.add(share)
        await self.session.flush()
        return share

    async def get_share(self, share_id: uuid.UUID) -> Optional[AppShare]:
        result = await self.session.execute(
            select(AppShare).where(AppShare.id == share_id)
        )
        return result.scalar_one_or_none()

    async def list_shares_for_app(
        self, app_id: uuid.UUID, include_revoked: bool = True
    ) -> List[AppShare]:
        query = select(AppShare).where(AppShare.app_id == app_id)
        if not include_revoked:
            query = query.where(AppShare.status == "active")
        result = await self.session.execute(query.order_by(AppShare.granted_at.desc()))
        return list(result.scalars().all())

    async def revoke_share(self, share_id: uuid.UUID) -> Optional[AppShare]:
        share = await self.get_share(share_id)
        if share:
            share.status = "revoked"
            await self.session.flush()
        return share

    async def revoke_all_shares_for_user(self, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            update(AppShare)
            .where(
                and_(
                    AppShare.user_id == user_id,
                    AppShare.status == "active",
                )
            )
            .values(status="revoked")
        )
        await self.session.flush()
        return result.rowcount

    async def upsert_group_share(
        self,
        app_id: uuid.UUID,
        user_id: uuid.UUID,
        app_role: str,
        group_id: uuid.UUID,
    ) -> AppShare:
        existing = await self.session.execute(
            select(AppShare).where(
                and_(
                    AppShare.app_id == app_id,
                    AppShare.user_id == user_id,
                    AppShare.app_role == app_role,
                )
            )
        )
        share = existing.scalar_one_or_none()
        metadata = {"source": "scim_group", "group_id": str(group_id)}
        if share:
            share.status = "active"
            share.metadata_ = metadata
            share.granted_at = datetime.now(timezone.utc)
            await self.session.flush()
            return share
        else:
            share = AppShare(
                app_id=app_id,
                user_id=user_id,
                app_role=app_role,
                status="active",
                metadata_=metadata,
            )
            self.session.add(share)
            await self.session.flush()
            return share

    async def revoke_group_share(
        self,
        app_id: uuid.UUID,
        user_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> None:
        result = await self.session.execute(
            select(AppShare).where(
                and_(
                    AppShare.app_id == app_id,
                    AppShare.user_id == user_id,
                    AppShare.status == "active",
                )
            )
        )
        shares = result.scalars().all()
        for share in shares:
            meta = share.metadata_ or {}
            if meta.get("source") == "scim_group" and meta.get("group_id") == str(group_id):
                share.status = "revoked"
        await self.session.flush()

    async def find_active_shares_for_user(
        self, app_id: uuid.UUID, user_id: uuid.UUID
    ) -> List[AppShare]:
        result = await self.session.execute(
            select(AppShare).where(
                and_(
                    AppShare.app_id == app_id,
                    AppShare.user_id == user_id,
                    AppShare.status == "active",
                )
            )
        )
        return list(result.scalars().all())

    async def get_share_policy(self, app_id: uuid.UUID) -> Optional[AppSharePolicy]:
        result = await self.session.execute(
            select(AppSharePolicy).where(AppSharePolicy.app_id == app_id)
        )
        return result.scalar_one_or_none()

    async def set_share_policy(
        self,
        app_id: uuid.UUID,
        default_scope: str = "org",
        external_users_allowed: bool = False,
        updated_by_user_id: Optional[uuid.UUID] = None,
    ) -> AppSharePolicy:
        policy = AppSharePolicy(
            app_id=app_id,
            default_scope=default_scope,
            external_users_allowed=external_users_allowed,
            updated_by_user_id=updated_by_user_id,
        )
        await self.session.merge(policy)
        await self.session.flush()
        return policy


class AuditDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def record_event(
        self,
        action: str,
        outcome: str = "success",
        organization_id: Optional[uuid.UUID] = None,
        app_id: Optional[uuid.UUID] = None,
        actor_user_id: Optional[uuid.UUID] = None,
        actor_agent: Optional[str] = None,
        actor_tool: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        occurred_at: Optional[datetime] = None,
    ) -> AuditEvent:
        clean_metadata = redact_audit_metadata(metadata or {})
        event_time = occurred_at or datetime.now(timezone.utc)
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        # Hash chain sequence calculation
        if organization_id:
            latest_res = await self.session.execute(
                select(AuditEvent.sequence_number, AuditEvent.event_hash)
                .where(AuditEvent.organization_id == organization_id)
                .order_by(AuditEvent.sequence_number.desc())
                .limit(1)
            )
            latest = latest_res.first()
            if latest:
                prev_seq = latest[0]
                prev_hash = latest[1]
            else:
                cp_res = await self.session.execute(
                    select(
                        OrganizationAuditCheckpoint.checkpoint_sequence,
                        OrganizationAuditCheckpoint.checkpoint_hash,
                    )
                    .where(OrganizationAuditCheckpoint.organization_id == organization_id)
                    .order_by(OrganizationAuditCheckpoint.checkpoint_sequence.desc())
                    .limit(1)
                )
                cp = cp_res.first()
                if cp:
                    prev_seq = cp[0]
                    prev_hash = cp[1]
                else:
                    prev_seq = 0
                    prev_hash = GENESIS_HASH
            seq_num = prev_seq + 1
        else:
            seq_num = 1
            prev_hash = GENESIS_HASH

        event_hash = compute_audit_event_hash(
            organization_id=organization_id,
            sequence_number=seq_num,
            prev_hash=prev_hash,
            action=action,
            outcome=outcome,
            app_id=app_id,
            actor_user_id=actor_user_id,
            actor_agent=actor_agent,
            actor_tool=actor_tool,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            user_agent=user_agent,
            occurred_at=event_time,
            metadata=clean_metadata,
        )

        event = AuditEvent(
            action=action,
            outcome=outcome,
            organization_id=organization_id,
            app_id=app_id,
            actor_user_id=actor_user_id,
            actor_agent=actor_agent,
            actor_tool=actor_tool,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_=clean_metadata,
            sequence_number=seq_num,
            prev_hash=prev_hash,
            event_hash=event_hash,
            occurred_at=event_time,
        )
        self.session.add(event)
        await self.session.flush()

        # Optional streaming webhook notification
        if organization_id:
            try:
                wh_res = await self.session.execute(
                    select(OrganizationAuditWebhook).where(
                        OrganizationAuditWebhook.organization_id == organization_id,
                        OrganizationAuditWebhook.is_active == True,
                    )
                )
                webhook = wh_res.scalar_one_or_none()
                if webhook:
                    secret = (
                        decrypt_secret(webhook.secret_token_encrypted)
                        if webhook.secret_token_encrypted
                        else None
                    )
                    payload_dict = {
                        "id": str(event.id),
                        "organization_id": str(organization_id),
                        "sequence_number": seq_num,
                        "prev_hash": prev_hash,
                        "event_hash": event_hash,
                        "action": action,
                        "outcome": outcome,
                        "app_id": str(app_id) if app_id else None,
                        "actor_user_id": str(actor_user_id) if actor_user_id else None,
                        "actor_agent": actor_agent,
                        "actor_tool": actor_tool,
                        "target_type": target_type,
                        "target_id": str(target_id) if target_id else None,
                        "ip_address": ip_address,
                        "user_agent": user_agent,
                        "metadata": clean_metadata,
                        "occurred_at": format_audit_timestamp(event_time),
                    }
                    asyncio.create_task(
                        dispatch_audit_webhook(webhook.url, secret, payload_dict)
                    )
            except Exception:
                pass

        return event

    async def list_events(
        self,
        organization_id: Optional[uuid.UUID] = None,
        app_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> List[AuditEvent]:
        query = select(AuditEvent)
        if organization_id:
            query = query.where(AuditEvent.organization_id == organization_id)
        if app_id:
            query = query.where(AuditEvent.app_id == app_id)
        query = query.order_by(AuditEvent.occurred_at.desc()).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_events_filtered(
        self,
        organization_id: Optional[uuid.UUID] = None,
        app_id: Optional[uuid.UUID] = None,
        actor_user_id: Optional[uuid.UUID] = None,
        agent_or_tool: Optional[str] = None,
        action: Optional[str] = None,
        outcome: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        app_ids_scope: Optional[List[uuid.UUID]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[AuditEvent], int]:
        filters = []
        if organization_id is not None:
            filters.append(AuditEvent.organization_id == organization_id)
        if app_id is not None:
            filters.append(AuditEvent.app_id == app_id)
        if app_ids_scope is not None:
            filters.append(AuditEvent.app_id.in_(app_ids_scope))
        if actor_user_id is not None:
            filters.append(AuditEvent.actor_user_id == actor_user_id)
        if agent_or_tool:
            filters.append(
                or_(
                    AuditEvent.actor_agent == agent_or_tool,
                    AuditEvent.actor_tool == agent_or_tool,
                )
            )
        if action:
            filters.append(AuditEvent.action == action)
        if outcome:
            filters.append(AuditEvent.outcome == outcome)
        if start_time is not None:
            filters.append(AuditEvent.occurred_at >= start_time)
        if end_time is not None:
            filters.append(AuditEvent.occurred_at <= end_time)

        # Count query
        count_q = select(func.count(AuditEvent.id))
        if filters:
            count_q = count_q.where(and_(*filters))
        count_res = await self.session.execute(count_q)
        total_count = count_res.scalar() or 0

        # Data query
        data_q = select(AuditEvent)
        if filters:
            data_q = data_q.where(and_(*filters))
        data_q = data_q.order_by(AuditEvent.occurred_at.desc()).offset(offset).limit(limit)
        data_res = await self.session.execute(data_q)
        return list(data_res.scalars().all()), total_count

    async def verify_chain(self, organization_id: uuid.UUID) -> Dict[str, Any]:
        """
        Verifies cryptographic hash chain integrity for an organization.
        Detects any modified rows, dropped rows, gaps, or reorderings.
        """
        # Fetch latest checkpoint if any
        cp_res = await self.session.execute(
            select(OrganizationAuditCheckpoint)
            .where(OrganizationAuditCheckpoint.organization_id == organization_id)
            .order_by(OrganizationAuditCheckpoint.checkpoint_sequence.desc())
            .limit(1)
        )
        checkpoint = cp_res.scalar_one_or_none()

        # Fetch all events ordered by sequence_number ascending
        events_res = await self.session.execute(
            select(AuditEvent)
            .where(AuditEvent.organization_id == organization_id)
            .order_by(AuditEvent.sequence_number.asc())
        )
        events = list(events_res.scalars().all())

        if not events and not checkpoint:
            return {
                "valid": True,
                "organization_id": str(organization_id),
                "total_events": 0,
                "first_sequence": None,
                "last_sequence": None,
                "tampered_at_sequence": None,
                "message": "No audit records found",
            }

        expected_prev = checkpoint.checkpoint_hash if checkpoint else GENESIS_HASH
        expected_seq = (checkpoint.checkpoint_sequence + 1) if checkpoint else 1

        for event in events:
            if event.sequence_number != expected_seq:
                return {
                    "valid": False,
                    "organization_id": str(organization_id),
                    "tampered_at_sequence": event.sequence_number,
                    "reason": f"Sequence gap: expected sequence {expected_seq}, found {event.sequence_number}",
                }

            if event.prev_hash != expected_prev:
                return {
                    "valid": False,
                    "organization_id": str(organization_id),
                    "tampered_at_sequence": event.sequence_number,
                    "reason": f"Hash chain broken at sequence {event.sequence_number}: expected prev_hash {expected_prev}, found {event.prev_hash}",
                }

            recomputed = compute_audit_event_hash(
                organization_id=event.organization_id,
                sequence_number=event.sequence_number,
                prev_hash=event.prev_hash,
                action=event.action,
                outcome=event.outcome,
                app_id=event.app_id,
                actor_user_id=event.actor_user_id,
                actor_agent=event.actor_agent,
                actor_tool=event.actor_tool,
                target_type=event.target_type,
                target_id=event.target_id,
                ip_address=event.ip_address,
                user_agent=event.user_agent,
                occurred_at=event.occurred_at,
                metadata=event.metadata_,
            )

            if recomputed != event.event_hash:
                return {
                    "valid": False,
                    "organization_id": str(organization_id),
                    "tampered_at_sequence": event.sequence_number,
                    "reason": f"Event data modified at sequence {event.sequence_number}: hash mismatch",
                }

            expected_prev = event.event_hash
            expected_seq += 1

        return {
            "valid": True,
            "organization_id": str(organization_id),
            "total_events": len(events),
            "first_sequence": events[0].sequence_number if events else None,
            "last_sequence": events[-1].sequence_number if events else None,
            "tampered_at_sequence": None,
            "checkpoint": {
                "sequence": checkpoint.checkpoint_sequence,
                "hash": checkpoint.checkpoint_hash,
            }
            if checkpoint
            else None,
        }

    async def get_by_id(self, event_id: uuid.UUID) -> Optional[AuditEvent]:
        res = await self.session.execute(
            select(AuditEvent).where(AuditEvent.id == event_id)
        )
        return res.scalar_one_or_none()

    async def get_by_idempotency_key(self, idempotency_key: str) -> Optional[AuditEvent]:
        result = await self.session.execute(
            select(AuditEvent).where(
                AuditEvent.metadata_["idempotency_key"].as_string() == idempotency_key
            )
        )
        return result.scalar_one_or_none()

    async def get_by_operation_id(self, operation_id: str) -> Optional[AuditEvent]:
        result = await self.session.execute(
            select(AuditEvent).where(
                AuditEvent.metadata_["operation_id"].as_string() == operation_id
            )
        )
        return result.scalar_one_or_none()


class AuditWebhookDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_org(
        self, organization_id: uuid.UUID
    ) -> Optional[OrganizationAuditWebhook]:
        res = await self.session.execute(
            select(OrganizationAuditWebhook).where(
                OrganizationAuditWebhook.organization_id == organization_id
            )
        )
        return res.scalar_one_or_none()

    async def upsert_webhook(
        self,
        organization_id: uuid.UUID,
        url: str,
        secret_token: Optional[str] = None,
        is_active: bool = True,
    ) -> OrganizationAuditWebhook:
        existing = await self.get_by_org(organization_id)
        encrypted_secret = encrypt_secret(secret_token) if secret_token else None
        if existing:
            existing.url = url
            if secret_token is not None:
                existing.secret_token_encrypted = encrypted_secret
            existing.is_active = is_active
            await self.session.flush()
            return existing
        new_wh = OrganizationAuditWebhook(
            organization_id=organization_id,
            url=url,
            secret_token_encrypted=encrypted_secret,
            is_active=is_active,
        )
        self.session.add(new_wh)
        await self.session.flush()
        return new_wh

    async def delete_webhook(self, organization_id: uuid.UUID) -> bool:
        existing = await self.get_by_org(organization_id)
        if existing:
            await self.session.delete(existing)
            await self.session.flush()
            return True
        return False


class CapabilityApprovalDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        app_id: uuid.UUID,
        capability_key: str,
        requested_version_id: Optional[uuid.UUID] = None,
        previous_value: Optional[Dict[str, Any]] = None,
        requested_value: Optional[Dict[str, Any]] = None,
        requested_by_user_id: Optional[uuid.UUID] = None,
    ) -> CapabilityApproval:
        approval = CapabilityApproval(
            app_id=app_id,
            requested_version_id=requested_version_id,
            capability_key=capability_key,
            previous_value=previous_value,
            requested_value=requested_value,
            status="pending",
            requested_by_user_id=requested_by_user_id,
        )
        self.session.add(approval)
        await self.session.flush()
        return approval

    async def get_by_id(self, approval_id: uuid.UUID) -> Optional[CapabilityApproval]:
        result = await self.session.execute(
            select(CapabilityApproval).where(CapabilityApproval.id == approval_id)
        )
        return result.scalar_one_or_none()

    async def list_for_app(
        self, app_id: uuid.UUID, status: Optional[str] = None
    ) -> List[CapabilityApproval]:
        stmt = select(CapabilityApproval).where(CapabilityApproval.app_id == app_id)
        if status:
            stmt = stmt.where(CapabilityApproval.status == status)
        stmt = stmt.order_by(CapabilityApproval.requested_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_version(
        self, version_id: uuid.UUID
    ) -> List[CapabilityApproval]:
        stmt = select(CapabilityApproval).where(
            CapabilityApproval.requested_version_id == version_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def decide(
        self, approval_id: uuid.UUID, decision: str, decided_by_user_id: uuid.UUID
    ) -> Optional[CapabilityApproval]:
        approval = await self.get_by_id(approval_id)
        if not approval:
            return None
        approval.status = decision
        approval.approved_by_user_id = decided_by_user_id
        approval.decided_at = datetime.now(timezone.utc)
        await self.session.flush()
        return approval


class ConnectorCredentialDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def set_credential(
        self,
        organization_id: uuid.UUID,
        connector_name: str,
        identity_type: str,
        credential_data: Any,
        user_id: Optional[uuid.UUID] = None,
        app_id: Optional[uuid.UUID] = None,
    ) -> ConnectorCredential:
        encrypted = encrypt_secret(credential_data)
        query = select(ConnectorCredential).where(
            ConnectorCredential.organization_id == organization_id,
            ConnectorCredential.connector_name == connector_name,
            ConnectorCredential.identity_type == identity_type,
            ConnectorCredential.user_id == user_id,
        )
        res = await self.session.execute(query)
        existing = res.scalar_one_or_none()
        if existing:
            existing.encrypted_data = encrypted
            existing.app_id = app_id
            existing.updated_at = datetime.now(timezone.utc)
            await self.session.flush()
            return existing

        cred = ConnectorCredential(
            organization_id=organization_id,
            app_id=app_id,
            connector_name=connector_name,
            identity_type=identity_type,
            user_id=user_id,
            encrypted_data=encrypted,
            key_id="v1",
        )
        self.session.add(cred)
        await self.session.flush()
        return cred

    async def get_credential(
        self,
        organization_id: uuid.UUID,
        connector_name: str,
        identity_type: str = "service",
        user_id: Optional[uuid.UUID] = None,
    ) -> Optional[Any]:
        query = select(ConnectorCredential).where(
            ConnectorCredential.organization_id == organization_id,
            ConnectorCredential.connector_name == connector_name,
            ConnectorCredential.identity_type == identity_type,
            ConnectorCredential.user_id == user_id,
        )
        res = await self.session.execute(query)
        cred = res.scalar_one_or_none()
        if not cred:
            return None
        return decrypt_secret(cred.encrypted_data)

    async def get_credential_record(
        self,
        organization_id: uuid.UUID,
        connector_name: str,
        identity_type: str = "service",
        user_id: Optional[uuid.UUID] = None,
    ) -> Optional[ConnectorCredential]:
        query = select(ConnectorCredential).where(
            ConnectorCredential.organization_id == organization_id,
            ConnectorCredential.connector_name == connector_name,
            ConnectorCredential.identity_type == identity_type,
            ConnectorCredential.user_id == user_id,
        )
        res = await self.session.execute(query)
        return res.scalar_one_or_none()

    async def delete_credential(
        self,
        organization_id: uuid.UUID,
        connector_name: str,
        identity_type: str = "service",
        user_id: Optional[uuid.UUID] = None,
    ) -> bool:
        record = await self.get_credential_record(organization_id, connector_name, identity_type, user_id)
        if not record:
            return False
        await self.session.delete(record)
        await self.session.flush()
        return True

    async def list_credentials_metadata(
        self, organization_id: uuid.UUID
    ) -> List[Dict[str, Any]]:
        query = (
            select(ConnectorCredential)
            .where(ConnectorCredential.organization_id == organization_id)
            .order_by(ConnectorCredential.connector_name.asc())
        )
        res = await self.session.execute(query)
        records = res.scalars().all()
        return [
            {
                "id": str(r.id),
                "connector_name": r.connector_name,
                "identity_type": r.identity_type,
                "user_id": str(r.user_id) if r.user_id else None,
                "app_id": str(r.app_id) if r.app_id else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in records
        ]

    async def delete_all_credentials_for_user(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> int:
        query = select(ConnectorCredential).where(
            ConnectorCredential.organization_id == organization_id,
            ConnectorCredential.user_id == user_id,
        )
        res = await self.session.execute(query)
        records = res.scalars().all()
        count = len(records)
        for r in records:
            await self.session.delete(r)
        if count > 0:
            await self.session.flush()
        return count


class IdpDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_org(self, org_id: uuid.UUID) -> Optional[OrganizationIdentityProvider]:
        result = await self.session.execute(
            select(OrganizationIdentityProvider)
            .where(
                and_(
                    OrganizationIdentityProvider.organization_id == org_id,
                    OrganizationIdentityProvider.is_active == True,
                )
            )
            .order_by(OrganizationIdentityProvider.updated_at.desc())
        )
        return result.scalars().first()

    async def get_by_org_and_type(
        self, org_id: uuid.UUID, provider_type: str
    ) -> Optional[OrganizationIdentityProvider]:
        result = await self.session.execute(
            select(OrganizationIdentityProvider).where(
                and_(
                    OrganizationIdentityProvider.organization_id == org_id,
                    OrganizationIdentityProvider.provider_type == provider_type,
                )
            )
        )
        return result.scalar_one_or_none()

    async def upsert_idp(
        self,
        org_id: uuid.UUID,
        provider_type: str,
        is_active: bool = True,
        enforce_sso: bool = False,
        session_lifetime_seconds: int = 28800,
        oidc_issuer_url: Optional[str] = None,
        oidc_client_id: Optional[str] = None,
        oidc_client_secret: Optional[str] = None,
        oidc_discovery_url: Optional[str] = None,
        oidc_scopes: Optional[List[str]] = None,
        saml_entity_id: Optional[str] = None,
        saml_sso_url: Optional[str] = None,
        saml_slo_url: Optional[str] = None,
        saml_x509_cert: Optional[str] = None,
        saml_sp_entity_id: Optional[str] = "urn:capsule:sp",
        saml_acs_url: Optional[str] = None,
    ) -> OrganizationIdentityProvider:
        if is_active:
            await self.session.execute(
                update(OrganizationIdentityProvider)
                .where(
                    and_(
                        OrganizationIdentityProvider.organization_id == org_id,
                        OrganizationIdentityProvider.provider_type != provider_type,
                    )
                )
                .values(is_active=False)
            )

        idp = await self.get_by_org_and_type(org_id, provider_type)
        secret_enc = encrypt_secret(oidc_client_secret) if oidc_client_secret else None
        now = datetime.now(timezone.utc)

        if idp:
            idp.is_active = is_active
            idp.enforce_sso = enforce_sso
            idp.session_lifetime_seconds = session_lifetime_seconds
            idp.oidc_issuer_url = oidc_issuer_url
            idp.oidc_client_id = oidc_client_id
            if oidc_client_secret is not None:
                idp.oidc_client_secret_encrypted = secret_enc
            idp.oidc_discovery_url = oidc_discovery_url
            if oidc_scopes is not None:
                idp.oidc_scopes = oidc_scopes
            idp.saml_entity_id = saml_entity_id
            idp.saml_sso_url = saml_sso_url
            idp.saml_slo_url = saml_slo_url
            idp.saml_x509_cert = saml_x509_cert
            idp.saml_sp_entity_id = saml_sp_entity_id or "urn:capsule:sp"
            idp.saml_acs_url = saml_acs_url
            idp.updated_at = now
            await self.session.flush()
            return idp
        else:
            new_idp = OrganizationIdentityProvider(
                organization_id=org_id,
                provider_type=provider_type,
                is_active=is_active,
                enforce_sso=enforce_sso,
                session_lifetime_seconds=session_lifetime_seconds,
                oidc_issuer_url=oidc_issuer_url,
                oidc_client_id=oidc_client_id,
                oidc_client_secret_encrypted=secret_enc,
                oidc_discovery_url=oidc_discovery_url,
                oidc_scopes=oidc_scopes or ["openid", "email", "profile"],
                saml_entity_id=saml_entity_id,
                saml_sso_url=saml_sso_url,
                saml_slo_url=saml_slo_url,
                saml_x509_cert=saml_x509_cert,
                saml_sp_entity_id=saml_sp_entity_id or "urn:capsule:sp",
                saml_acs_url=saml_acs_url,
            )
            self.session.add(new_idp)
            await self.session.flush()
            return new_idp

    async def get_decrypted_client_secret(self, idp: OrganizationIdentityProvider) -> Optional[str]:
        if not idp.oidc_client_secret_encrypted:
            return None
        return decrypt_secret(idp.oidc_client_secret_encrypted)

    async def delete_idp(self, org_id: uuid.UUID, provider_type: Optional[str] = None) -> bool:
        query = select(OrganizationIdentityProvider).where(OrganizationIdentityProvider.organization_id == org_id)
        if provider_type:
            query = query.where(OrganizationIdentityProvider.provider_type == provider_type)
        res = await self.session.execute(query)
        records = res.scalars().all()
        if not records:
            return False
        for r in records:
            await self.session.delete(r)
        await self.session.flush()
        return True


class DomainDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_claim(self, org_id: uuid.UUID, domain: str) -> OrganizationVerifiedDomain:
        clean_domain = domain.lower().strip()
        token = f"capsule-domain-verification={secrets.token_hex(16)}"
        claim = OrganizationVerifiedDomain(
            organization_id=org_id,
            domain=clean_domain,
            verification_token=token,
            status="pending",
        )
        self.session.add(claim)
        await self.session.flush()
        return claim

    async def get_by_domain(self, domain: str) -> Optional[OrganizationVerifiedDomain]:
        clean_domain = domain.lower().strip()
        result = await self.session.execute(
            select(OrganizationVerifiedDomain).where(OrganizationVerifiedDomain.domain == clean_domain)
        )
        return result.scalar_one_or_none()

    async def list_for_org(self, org_id: uuid.UUID) -> List[OrganizationVerifiedDomain]:
        result = await self.session.execute(
            select(OrganizationVerifiedDomain)
            .where(OrganizationVerifiedDomain.organization_id == org_id)
            .order_by(OrganizationVerifiedDomain.created_at.desc())
        )
        return list(result.scalars().all())

    async def mark_verified(self, domain: str) -> Optional[OrganizationVerifiedDomain]:
        claim = await self.get_by_domain(domain)
        if claim:
            now = datetime.now(timezone.utc)
            claim.status = "verified"
            claim.verified_at = now
            claim.updated_at = now
            await self.session.flush()
        return claim

    async def delete_domain(self, org_id: uuid.UUID, domain: str) -> bool:
        claim = await self.get_by_domain(domain)
        if claim and claim.organization_id == org_id:
            await self.session.delete(claim)
            await self.session.flush()
            return True
        return False

    async def is_domain_verified_for_org(self, org_id: uuid.UUID, domain: str) -> bool:
        clean_domain = domain.lower().strip()
        result = await self.session.execute(
            select(OrganizationVerifiedDomain).where(
                and_(
                    OrganizationVerifiedDomain.organization_id == org_id,
                    OrganizationVerifiedDomain.domain == clean_domain,
                    OrganizationVerifiedDomain.status == "verified",
                )
            )
        )
        return result.scalar_one_or_none() is not None


class ReplayDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_replayed(self, assertion_id: str) -> bool:
        result = await self.session.execute(
            select(SSOReplayCache).where(SSOReplayCache.assertion_id == assertion_id)
        )
        return result.scalar_one_or_none() is not None

    async def record_assertion(
        self, assertion_id: str, org_id: uuid.UUID, expires_at: datetime
    ) -> bool:
        if await self.is_replayed(assertion_id):
            return False
        entry = SSOReplayCache(
            assertion_id=assertion_id,
            organization_id=org_id,
            expires_at=expires_at,
        )
        self.session.add(entry)
        await self.session.flush()
        return True


class SCIMTokenDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def rotate_token(self, org_id: uuid.UUID) -> tuple[str, OrganizationSCIMToken]:
        # Revoke existing active tokens for this organization
        await self.session.execute(
            update(OrganizationSCIMToken)
            .where(
                and_(
                    OrganizationSCIMToken.organization_id == org_id,
                    OrganizationSCIMToken.status == "active",
                )
            )
            .values(status="revoked")
        )

        # Generate 32-byte cryptographically secure token
        raw_token = f"scim_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token_prefix = raw_token[:10]

        record = OrganizationSCIMToken(
            organization_id=org_id,
            token_hash=token_hash,
            token_prefix=token_prefix,
            status="active",
        )
        self.session.add(record)
        await self.session.flush()
        return raw_token, record

    async def get_org_by_token(self, raw_token: str) -> Optional[Organization]:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        result = await self.session.execute(
            select(Organization)
            .join(OrganizationSCIMToken, OrganizationSCIMToken.organization_id == Organization.id)
            .where(
                and_(
                    OrganizationSCIMToken.token_hash == token_hash,
                    OrganizationSCIMToken.status == "active",
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_token_record(self, org_id: uuid.UUID) -> Optional[OrganizationSCIMToken]:
        result = await self.session.execute(
            select(OrganizationSCIMToken)
            .where(
                and_(
                    OrganizationSCIMToken.organization_id == org_id,
                    OrganizationSCIMToken.status == "active",
                )
            )
            .order_by(OrganizationSCIMToken.created_at.desc())
        )
        return result.scalar_one_or_none()


class SCIMGroupDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_group(
        self, org_id: uuid.UUID, display_name: str, external_id: Optional[str] = None
    ) -> SCIMGroup:
        group = SCIMGroup(
            organization_id=org_id,
            display_name=display_name,
            external_id=external_id,
        )
        self.session.add(group)
        await self.session.flush()
        return group

    async def get_by_id(self, group_id: uuid.UUID) -> Optional[SCIMGroup]:
        result = await self.session.execute(select(SCIMGroup).where(SCIMGroup.id == group_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, org_id: uuid.UUID, display_name: str) -> Optional[SCIMGroup]:
        result = await self.session.execute(
            select(SCIMGroup).where(
                and_(
                    SCIMGroup.organization_id == org_id,
                    func.lower(SCIMGroup.display_name) == display_name.lower(),
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_for_org(self, org_id: uuid.UUID) -> List[SCIMGroup]:
        result = await self.session.execute(
            select(SCIMGroup)
            .where(SCIMGroup.organization_id == org_id)
            .order_by(SCIMGroup.display_name.asc())
        )
        return list(result.scalars().all())

    async def update_group(
        self,
        group_id: uuid.UUID,
        display_name: Optional[str] = None,
        external_id: Optional[str] = None,
    ) -> Optional[SCIMGroup]:
        group = await self.get_by_id(group_id)
        if not group:
            return None
        now = datetime.now(timezone.utc)
        if display_name is not None:
            group.display_name = display_name
        if external_id is not None:
            group.external_id = external_id
        group.updated_at = now
        await self.session.flush()
        return group

    async def delete_group(self, group_id: uuid.UUID) -> bool:
        group = await self.get_by_id(group_id)
        if not group:
            return False
        await self.session.delete(group)
        await self.session.flush()
        return True

    async def get_members(self, group_id: uuid.UUID) -> List[User]:
        result = await self.session.execute(
            select(User)
            .join(SCIMGroupMember, SCIMGroupMember.user_id == User.id)
            .where(SCIMGroupMember.group_id == group_id)
            .order_by(User.email.asc())
        )
        return list(result.scalars().all())

    async def add_member(self, group_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        existing = await self.session.execute(
            select(SCIMGroupMember).where(
                and_(
                    SCIMGroupMember.group_id == group_id,
                    SCIMGroupMember.user_id == user_id,
                )
            )
        )
        if existing.scalar_one_or_none():
            return False
        self.session.add(SCIMGroupMember(group_id=group_id, user_id=user_id))
        await self.session.flush()
        return True

    async def remove_member(self, group_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        existing = await self.session.execute(
            select(SCIMGroupMember).where(
                and_(
                    SCIMGroupMember.group_id == group_id,
                    SCIMGroupMember.user_id == user_id,
                )
            )
        )
        member = existing.scalar_one_or_none()
        if not member:
            return False
        await self.session.delete(member)
        await self.session.flush()
        return True

    async def set_members(
        self, group_id: uuid.UUID, target_user_ids: List[uuid.UUID]
    ) -> tuple[List[uuid.UUID], List[uuid.UUID]]:
        current_members = await self.get_members(group_id)
        current_ids = {m.id for m in current_members}
        target_ids = set(target_user_ids)

        added = target_ids - current_ids
        removed = current_ids - target_ids

        for u_id in removed:
            await self.remove_member(group_id, u_id)
        for u_id in added:
            await self.add_member(group_id, u_id)

        return list(added), list(removed)

    async def list_groups_for_user(self, user_id: uuid.UUID) -> List[SCIMGroup]:
        result = await self.session.execute(
            select(SCIMGroup)
            .join(SCIMGroupMember, SCIMGroupMember.group_id == SCIMGroup.id)
            .where(SCIMGroupMember.user_id == user_id)
        )
        return list(result.scalars().all())


class GroupRoleMappingDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_mapping(
        self,
        org_id: uuid.UUID,
        group_id: uuid.UUID,
        app_id: uuid.UUID,
        app_role: str,
    ) -> SCIMGroupRoleMapping:
        existing = await self.session.execute(
            select(SCIMGroupRoleMapping).where(
                and_(
                    SCIMGroupRoleMapping.group_id == group_id,
                    SCIMGroupRoleMapping.app_id == app_id,
                    SCIMGroupRoleMapping.app_role == app_role,
                )
            )
        )
        mapping = existing.scalar_one_or_none()
        if mapping:
            return mapping

        mapping = SCIMGroupRoleMapping(
            organization_id=org_id,
            group_id=group_id,
            app_id=app_id,
            app_role=app_role,
        )
        self.session.add(mapping)
        await self.session.flush()
        return mapping

    async def list_for_org(self, org_id: uuid.UUID) -> List[SCIMGroupRoleMapping]:
        result = await self.session.execute(
            select(SCIMGroupRoleMapping)
            .where(SCIMGroupRoleMapping.organization_id == org_id)
            .order_by(SCIMGroupRoleMapping.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_group(self, group_id: uuid.UUID) -> List[SCIMGroupRoleMapping]:
        result = await self.session.execute(
            select(SCIMGroupRoleMapping)
            .where(SCIMGroupRoleMapping.group_id == group_id)
        )
        return list(result.scalars().all())

    async def delete_mapping(self, mapping_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(SCIMGroupRoleMapping).where(SCIMGroupRoleMapping.id == mapping_id)
        )
        mapping = result.scalar_one_or_none()
        if not mapping:
            return False
        await self.session.delete(mapping)
        await self.session.flush()
        return True


class AIUsageDAL:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def record_usage(
        self,
        organization_id: uuid.UUID,
        app_id: uuid.UUID,
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_usd: float,
        duration_ms: int,
        user_id: Optional[uuid.UUID] = None,
        status: str = "success",
        prompt_content: Optional[str] = None,
        response_content: Optional[str] = None,
        redacted: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AIUsageRecord:
        record = AIUsageRecord(
            organization_id=organization_id,
            app_id=app_id,
            user_id=user_id,
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=estimated_cost_usd,
            duration_ms=duration_ms,
            status=status,
            prompt_content=prompt_content,
            response_content=response_content,
            redacted=redacted,
            metadata_=metadata or {},
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_app_monthly_spend(
        self,
        app_id: uuid.UUID,
        month_start: datetime,
    ) -> float:
        result = await self.session.execute(
            select(func.coalesce(func.sum(AIUsageRecord.estimated_cost_usd), 0.0)).where(
                and_(
                    AIUsageRecord.app_id == app_id,
                    AIUsageRecord.created_at >= month_start,
                    AIUsageRecord.status == "success",
                )
            )
        )
        return float(result.scalar() or 0.0)

    async def get_app_monthly_tokens(
        self,
        app_id: uuid.UUID,
        month_start: datetime,
    ) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(AIUsageRecord.total_tokens), 0)).where(
                and_(
                    AIUsageRecord.app_id == app_id,
                    AIUsageRecord.created_at >= month_start,
                    AIUsageRecord.status == "success",
                )
            )
        )
        return int(result.scalar() or 0)

    async def get_app_usage_summary(
        self,
        app_id: uuid.UUID,
        month_start: datetime,
    ) -> Dict[str, Any]:
        spend = await self.get_app_monthly_spend(app_id, month_start)
        tokens = await self.get_app_monthly_tokens(app_id, month_start)

        req_count_res = await self.session.execute(
            select(func.count(AIUsageRecord.id)).where(
                and_(
                    AIUsageRecord.app_id == app_id,
                    AIUsageRecord.created_at >= month_start,
                )
            )
        )
        req_count = int(req_count_res.scalar() or 0)

        recent_res = await self.session.execute(
            select(AIUsageRecord)
            .where(AIUsageRecord.app_id == app_id)
            .order_by(AIUsageRecord.created_at.desc())
            .limit(10)
        )
        recent = list(recent_res.scalars().all())

        return {
            "monthly_spend_usd": spend,
            "monthly_tokens": tokens,
            "monthly_requests": req_count,
            "recent_requests": recent,
        }

    async def get_org_usage_summary(
        self,
        org_id: uuid.UUID,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        filters = [AIUsageRecord.organization_id == org_id]
        if start_time:
            filters.append(AIUsageRecord.created_at >= start_time)
        if end_time:
            filters.append(AIUsageRecord.created_at <= end_time)

        # Totals
        totals_query = select(
            func.count(AIUsageRecord.id).label("total_requests"),
            func.coalesce(func.sum(AIUsageRecord.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(AIUsageRecord.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(AIUsageRecord.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(AIUsageRecord.estimated_cost_usd), 0.0).label("total_cost"),
        ).where(and_(*filters))
        totals_res = await self.session.execute(totals_query)
        tot = totals_res.one()

        # By model
        by_model_query = (
            select(
                AIUsageRecord.model,
                func.count(AIUsageRecord.id).label("requests"),
                func.coalesce(func.sum(AIUsageRecord.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(AIUsageRecord.estimated_cost_usd), 0.0).label("cost"),
            )
            .where(and_(*filters))
            .group_by(AIUsageRecord.model)
            .order_by(func.sum(AIUsageRecord.estimated_cost_usd).desc())
        )
        by_model_res = await self.session.execute(by_model_query)
        by_model = [
            {
                "model": row.model,
                "requests": int(row.requests),
                "tokens": int(row.tokens),
                "cost_usd": float(row.cost),
            }
            for row in by_model_res.all()
        ]

        # By app
        by_app_query = (
            select(
                AIUsageRecord.app_id,
                App.name.label("app_name"),
                func.count(AIUsageRecord.id).label("requests"),
                func.coalesce(func.sum(AIUsageRecord.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(AIUsageRecord.estimated_cost_usd), 0.0).label("cost"),
            )
            .join(App, AIUsageRecord.app_id == App.id)
            .where(and_(*filters))
            .group_by(AIUsageRecord.app_id, App.name)
            .order_by(func.sum(AIUsageRecord.estimated_cost_usd).desc())
        )
        by_app_res = await self.session.execute(by_app_query)
        by_app = [
            {
                "app_id": str(row.app_id),
                "app_name": row.app_name,
                "requests": int(row.requests),
                "tokens": int(row.tokens),
                "cost_usd": float(row.cost),
            }
            for row in by_app_res.all()
        ]

        # By user
        by_user_query = (
            select(
                AIUsageRecord.user_id,
                User.email.label("user_email"),
                func.count(AIUsageRecord.id).label("requests"),
                func.coalesce(func.sum(AIUsageRecord.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(AIUsageRecord.estimated_cost_usd), 0.0).label("cost"),
            )
            .outerjoin(User, AIUsageRecord.user_id == User.id)
            .where(and_(*filters))
            .group_by(AIUsageRecord.user_id, User.email)
            .order_by(func.sum(AIUsageRecord.estimated_cost_usd).desc())
        )
        by_user_res = await self.session.execute(by_user_query)
        by_user = [
            {
                "user_id": str(row.user_id) if row.user_id else None,
                "user_email": row.user_email or "System / Service",
                "requests": int(row.requests),
                "tokens": int(row.tokens),
                "cost_usd": float(row.cost),
            }
            for row in by_user_res.all()
        ]

        return {
            "total_requests": int(tot.total_requests),
            "prompt_tokens": int(tot.prompt_tokens),
            "completion_tokens": int(tot.completion_tokens),
            "total_tokens": int(tot.total_tokens),
            "total_estimated_cost_usd": float(tot.total_cost),
            "by_model": by_model,
            "by_app": by_app,
            "by_user": by_user,
        }

    async def list_requests(
        self,
        org_id: uuid.UUID,
        app_id: Optional[uuid.UUID] = None,
        model: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[AIUsageRecord], int]:
        filters = [AIUsageRecord.organization_id == org_id]
        if app_id:
            filters.append(AIUsageRecord.app_id == app_id)
        if model:
            filters.append(AIUsageRecord.model == model)
        if user_id:
            filters.append(AIUsageRecord.user_id == user_id)
        if status:
            filters.append(AIUsageRecord.status == status)

        count_query = select(func.count(AIUsageRecord.id)).where(and_(*filters))
        total_res = await self.session.execute(count_query)
        total = int(total_res.scalar() or 0)

        records_query = (
            select(AIUsageRecord)
            .where(and_(*filters))
            .order_by(AIUsageRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        records_res = await self.session.execute(records_query)
        records = list(records_res.scalars().all())

        return records, total

    async def purge_expired_content(
        self,
        org_id: uuid.UUID,
        retention_days: int,
    ) -> int:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        result = await self.session.execute(
            update(AIUsageRecord)
            .where(
                and_(
                    AIUsageRecord.organization_id == org_id,
                    AIUsageRecord.created_at < cutoff,
                    or_(
                        AIUsageRecord.prompt_content.isnot(None),
                        AIUsageRecord.response_content.isnot(None),
                    ),
                )
            )
            .values(prompt_content=None, response_content=None)
        )
        await self.session.flush()
        return result.rowcount



