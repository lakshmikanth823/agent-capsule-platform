"""
Typed Data Access Layer (DAL) for Software Capsule Platform Control Plane
"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import select, update, delete, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Organization, User, OrganizationMember, App,
    AppShare, AppSharePolicy, AppVersion, AuditEvent, CapabilityApproval
)


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
    ) -> AuditEvent:
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
            metadata_=metadata or {},
        )
        self.session.add(event)
        await self.session.flush()
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

    async def get_by_idempotency_key(self, idempotency_key: str) -> Optional[AuditEvent]:
        # JSONB access in SQLAlchemy: AuditEvent.metadata_['idempotency_key'].astext
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
