"""
Governance Service (Prompt 20 / FR-033 to FR-036).
Implements ownership transfer, owner-left lifecycle handling (nominee transfer, grace periods, suspension),
expiry policies, inactivity tracking, background lifecycle cycles, inventory reporting, and CSV/JSON exports.
"""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, and_, or_, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import App, User, Organization, OrganizationMember, AppShare, AppVersion
from db.dal import AppDAL, UserDAL, OrganizationDAL, AuditDAL
from auth.models import AuthenticatedUser
from services.notification import get_notification_sender
from services.policy_engine import get_effective_profile, DEFAULT_ENVIRONMENT_PROFILE


class GovernanceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.app_dal = AppDAL(db)
        self.user_dal = UserDAL(db)
        self.org_dal = OrganizationDAL(db)
        self.audit_dal = AuditDAL(db)
        self.notifier = get_notification_sender()

    async def transfer_ownership(
        self,
        app_id: uuid.UUID,
        new_owner_user_id: uuid.UUID,
        actor_user: AuthenticatedUser,
        reason: str = "Manual ownership transfer",
    ) -> App:
        """
        Transfer app ownership.
        Allowed for: Current App Owner OR Organization Admin (platform_role == "owner").
        """
        app = await self.app_dal.get_by_id(app_id)
        if not app:
            raise ValueError(f"App {app_id} not found.")

        # Access check: Must be org admin or current app owner
        is_org_admin = (
            actor_user.platform_role == "owner"
            and app.organization_id == actor_user.organization_id
        )
        is_current_owner = app.owner_user_id == actor_user.id

        if not (is_org_admin or is_current_owner):
            raise PermissionError(
                "Only the current application owner or an organization administrator can transfer ownership."
            )

        # Validate target owner
        target_user = await self.user_dal.get_by_id(new_owner_user_id)
        if not target_user:
            raise ValueError(f"Target owner user {new_owner_user_id} not found.")

        if target_user.status != "active":
            raise ValueError(f"Target owner user {target_user.email} is not active (status: {target_user.status}).")

        # Verify target user is member of the organization
        if app.organization_id:
            member_check = await self.db.execute(
                select(OrganizationMember).where(
                    and_(
                        OrganizationMember.organization_id == app.organization_id,
                        OrganizationMember.user_id == new_owner_user_id,
                        OrganizationMember.status == "active",
                    )
                )
            )
            if not member_check.scalar_one_or_none():
                raise ValueError(f"Target owner user {target_user.email} is not an active member of this organization.")

        old_owner_id = str(app.owner_user_id) if app.owner_user_id else None
        transferred_app = await self.app_dal.transfer_ownership(
            app_id=app_id,
            new_owner_id=new_owner_user_id,
            clear_governance_pending=True,
        )

        now = datetime.now(timezone.utc)
        # Record structured audit event with hash chain
        await self.audit_dal.record_event(
            action="app.ownership_transferred",
            outcome="success",
            organization_id=app.organization_id,
            app_id=app.id,
            actor_user_id=actor_user.id,
            actor_agent="governance-service",
            actor_tool="capsule-cli/governance",
            target_type="app",
            target_id=app.id,
            occurred_at=now,
            metadata={
                "old_owner_id": old_owner_id,
                "new_owner_id": str(new_owner_user_id),
                "transferred_by_user_id": str(actor_user.id),
                "transferred_by_role": "admin" if is_org_admin else "owner",
                "reason": reason,
            },
        )

        # Notify new owner
        await self.notifier.send(
            recipient=target_user.email,
            subject=f"Application Ownership Transferred: {app.name}",
            template="ownership_transferred",
            context={
                "app_name": app.name,
                "app_key": app.app_key,
                "reason": reason,
            },
        )

        return transferred_app

    async def handle_owner_left(
        self,
        deprovisioned_user_id: uuid.UUID,
        org_id: uuid.UUID,
        reason: str = "User deprovisioned",
    ) -> List[Dict[str, Any]]:
        """
        FR-034 Owner-Left Handling.
        Triggered when an owner is deprovisioned (SCIM or manual removal).
        - If nominated owner is set and active: auto-transfer.
        - Else: enter configurable grace period (default 14 days), notify org admins/editors,
          app remains active until grace period ends.
        - An app is NEVER left without an owner or a pending decision.
        """
        deprovisioned_user = await self.user_dal.get_by_id(deprovisioned_user_id)
        owner_email = deprovisioned_user.email if deprovisioned_user else "unknown"

        org = await self.org_dal.get_by_id(org_id)
        effective_profile = get_effective_profile(org.environment_profile if org else {})
        gov_settings = effective_profile.get("governance", {})
        policy = (
            (org.environment_profile or {}).get("owner_left_policy")
            or gov_settings.get("owner_left_policy", "grace_period")
        )
        grace_period_days = gov_settings.get("owner_left_grace_period_days", 14)

        result = await self.db.execute(
            select(App).where(
                and_(
                    App.organization_id == org_id,
                    App.owner_user_id == deprovisioned_user_id,
                    App.status.in_(["active", "draft"]),
                )
            )
        )
        owned_apps = list(result.scalars().all())
        now = datetime.now(timezone.utc)
        affected_apps: List[Dict[str, Any]] = []

        # Find org admins and editors for notifications
        admin_editor_members = await self.db.execute(
            select(User)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(
                and_(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.platform_role.in_(["owner", "editor"]),
                    OrganizationMember.status == "active",
                    User.id != deprovisioned_user_id,
                )
            )
        )
        admin_editors = list(admin_editor_members.scalars().all())

        for app in owned_apps:
            # Case 1: Immediate suspension policy (FR-034 option)
            if policy == "suspend":
                app.status = "suspended"
                app.suspended_at = now
                app.suspended_by_user_id = None
                app.suspension_reason = (
                    f"App owner {owner_email} was deprovisioned via {reason}. "
                    f"Suspended to prevent unmanaged operation (FR-034)."
                )
                app.updated_at = now

                await self.audit_dal.record_event(
                    action="app.owner_deprovisioned",
                    outcome="success",
                    organization_id=org_id,
                    app_id=app.id,
                    actor_user_id=None,
                    actor_agent="scim-deprovisioning",
                    target_type="app",
                    target_id=app.id,
                    occurred_at=now,
                    metadata={
                        "orphaned_owner_id": str(deprovisioned_user_id),
                        "owner_email": owner_email,
                        "reason": reason,
                        "policy_applied": "suspend",
                    },
                )
                affected_apps.append({
                    "app_id": str(app.id),
                    "action": "suspended",
                    "reason": app.suspension_reason,
                })
                continue

            # Case 2: Nominated Owner is set and eligible
            if app.nominated_owner_user_id and app.nominated_owner_user_id != deprovisioned_user_id:
                nominee = await self.user_dal.get_by_id(app.nominated_owner_user_id)
                if nominee and nominee.status == "active":
                    old_owner_id = str(app.owner_user_id)
                    app.owner_user_id = nominee.id
                    app.governance_state = "normal"
                    app.governance_deadline = None
                    app.updated_at = now

                    await self.audit_dal.record_event(
                        action="app.ownership_transferred",
                        outcome="success",
                        organization_id=org_id,
                        app_id=app.id,
                        actor_user_id=None,
                        actor_agent="scim-deprovisioning",
                        target_type="app",
                        target_id=app.id,
                        occurred_at=now,
                        metadata={
                            "trigger": "owner_left_nominee",
                            "old_owner_id": old_owner_id,
                            "new_owner_id": str(nominee.id),
                            "reason": f"Transferred to nominee after {owner_email} left",
                        },
                    )

                    await self.notifier.send(
                        recipient=nominee.email,
                        subject=f"Application Ownership Transferred: {app.name}",
                        template="ownership_transferred",
                        context={
                            "app_name": app.name,
                            "app_key": app.app_key,
                            "reason": f"Automatic transfer to nominated owner following deprovisioning of {owner_email}.",
                        },
                    )

                    affected_apps.append({
                        "app_id": str(app.id),
                        "action": "transferred_to_nominee",
                        "new_owner_id": str(nominee.id),
                    })
                    continue

            # Case 3: No nominee -> Start Grace Period (app remains active)
            deadline = now + timedelta(days=grace_period_days)
            app.governance_state = "pending_owner"
            app.governance_deadline = deadline
            app.updated_at = now

            await self.audit_dal.record_event(
                action="app.governance_grace_period_started",
                outcome="success",
                organization_id=org_id,
                app_id=app.id,
                actor_user_id=None,
                actor_agent="scim-deprovisioning",
                target_type="app",
                target_id=app.id,
                occurred_at=now,
                metadata={
                    "orphaned_owner_id": str(deprovisioned_user_id),
                    "owner_email": owner_email,
                    "grace_period_days": grace_period_days,
                    "deadline": deadline.isoformat(),
                    "reason": reason,
                },
            )

            # Notify all org editors and admins
            for recipient in admin_editors:
                await self.notifier.send(
                    recipient=recipient.email,
                    subject=f"Action Required: App '{app.name}' Owner Left - {grace_period_days}-Day Grace Period",
                    template="owner_left_grace_period",
                    context={
                        "app_name": app.name,
                        "app_key": app.app_key,
                        "days_left": grace_period_days,
                        "deadline": deadline.isoformat(),
                    },
                )

            affected_apps.append({
                "app_id": str(app.id),
                "action": "grace_period_started",
                "deadline": deadline.isoformat(),
                "grace_period_days": grace_period_days,
            })

        await self.db.flush()
        return affected_apps

    async def update_governance_settings(
        self,
        app_id: uuid.UUID,
        actor_user: AuthenticatedUser,
        nominated_owner_user_id: Optional[uuid.UUID] = ...,
        expires_at: Optional[datetime] = ...,
        inactivity_days_limit: Optional[int] = ...,
        purge_after_days: Optional[int] = ...,
    ) -> App:
        """Update per-app governance configurations."""
        app = await self.app_dal.get_by_id(app_id)
        if not app:
            raise ValueError(f"App {app_id} not found.")

        is_org_admin = (
            actor_user.platform_role == "owner"
            and app.organization_id == actor_user.organization_id
        )
        is_owner = app.owner_user_id == actor_user.id
        if not (is_org_admin or is_owner):
            raise PermissionError("Only the app owner or org admin may update governance settings.")

        if nominated_owner_user_id is not ... and nominated_owner_user_id is not None:
            nominee = await self.user_dal.get_by_id(nominated_owner_user_id)
            if not nominee:
                raise ValueError(f"Nominated owner {nominated_owner_user_id} not found.")

        updated_app = await self.app_dal.set_governance_settings(
            app_id=app_id,
            nominated_owner_id=nominated_owner_user_id,
            expires_at=expires_at,
            inactivity_days_limit=inactivity_days_limit,
            purge_after_days=purge_after_days,
        )

        now = datetime.now(timezone.utc)
        await self.audit_dal.record_event(
            action="app.governance_settings_updated",
            outcome="success",
            organization_id=app.organization_id,
            app_id=app.id,
            actor_user_id=actor_user.id,
            actor_agent="governance-service",
            target_type="app",
            target_id=app.id,
            occurred_at=now,
            metadata={
                "nominated_owner_user_id": str(nominated_owner_user_id) if nominated_owner_user_id not in (..., None) else None,
                "expires_at": expires_at.isoformat() if expires_at not in (..., None) and isinstance(expires_at, datetime) else None,
                "inactivity_days_limit": inactivity_days_limit if inactivity_days_limit is not ... else None,
                "purge_after_days": purge_after_days if purge_after_days is not ... else None,
            },
        )
        return updated_app

    async def record_activity(
        self, app_id: uuid.UUID, timestamp: Optional[datetime] = None
    ) -> None:
        """Update last_activity_at on proxy or user interaction."""
        now = timestamp or datetime.now(timezone.utc)
        await self.app_dal.record_activity(app_id, now)

    async def run_governance_cycle(
        self,
        org_id: Optional[uuid.UUID] = None,
        current_time: Optional[datetime] = None,
    ) -> Dict[str, int]:
        """
        Background Scheduled Job / Lifecycle Worker.
        - Detects expired grace periods on unowned apps -> suspends app.
        - Sends expiry and inactivity warnings (14d, 7d, 1d).
        - Transitions expired apps to archived (suspends app, starts purge retention window).
        - Purges archived apps past retention window (offers export, marks deleting).
        """
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        stats = {
            "grace_periods_expired": 0,
            "warnings_sent": 0,
            "archived_count": 0,
            "purged_count": 0,
        }

        # Query all organizations or target org
        query = select(Organization).where(Organization.status == "active")
        if org_id:
            query = query.where(Organization.id == org_id)
        orgs = list((await self.db.execute(query)).scalars().all())

        for org in orgs:
            effective_profile = get_effective_profile(org.environment_profile)
            gov_settings = effective_profile.get("governance", {})
            warning_intervals: List[int] = sorted(
                gov_settings.get("warning_intervals_days", [14, 7, 1]), reverse=True
            )
            archive_retention_days = gov_settings.get("archive_retention_days", 30)
            org_default_inactivity_days = gov_settings.get("inactivity_suspend_days", 90)

            # Fetch all apps for this organization
            apps_result = await self.db.execute(
                select(App)
                .options(selectinload(App.owner))
                .where(App.organization_id == org.id)
            )
            apps = list(apps_result.scalars().all())

            # Fetch admins for notifications
            admin_result = await self.db.execute(
                select(User)
                .join(OrganizationMember, OrganizationMember.user_id == User.id)
                .where(
                    and_(
                        OrganizationMember.organization_id == org.id,
                        OrganizationMember.platform_role == "owner",
                        OrganizationMember.status == "active",
                    )
                )
            )
            admins = list(admin_result.scalars().all())

            for app in apps:
                # ----------------------------------------------------
                # Step 1: Detect unowned apps with expired grace period
                # ----------------------------------------------------
                if (
                    app.governance_state == "pending_owner"
                    and app.governance_deadline
                    and now >= app.governance_deadline
                    and app.status in ("active", "draft")
                ):
                    app.status = "suspended"
                    app.governance_state = "grace_period_expired"
                    app.suspended_at = now
                    app.suspension_reason = (
                        "Owner grace period expired without reassignment (FR-034). "
                        "Suspended to protect organization resources."
                    )
                    app.updated_at = now

                    await self.audit_dal.record_event(
                        action="app.owner_grace_period_expired",
                        outcome="success",
                        organization_id=org.id,
                        app_id=app.id,
                        actor_user_id=None,
                        actor_agent="governance-cycle",
                        target_type="app",
                        target_id=app.id,
                        occurred_at=now,
                        metadata={
                            "deadline": app.governance_deadline.isoformat(),
                            "expired_at": now.isoformat(),
                            "action": "suspended",
                        },
                    )

                    for admin in admins:
                        await self.notifier.send(
                            recipient=admin.email,
                            subject=f"App Suspended: {app.name} Grace Period Expired",
                            template="owner_grace_period_expired",
                            context={
                                "app_name": app.name,
                                "app_key": app.app_key,
                            },
                        )
                    stats["grace_periods_expired"] += 1
                    continue

                # ----------------------------------------------------
                # Step 2: Compute Effective Expiry & Activity Limit
                # ----------------------------------------------------
                effective_expiry: Optional[datetime] = app.expires_at

                inactivity_limit = app.inactivity_days_limit or org_default_inactivity_days
                if inactivity_limit:
                    activity_base = app.last_activity_at or app.created_at
                    inactivity_expiry = activity_base + timedelta(days=inactivity_limit)
                    if effective_expiry is None or inactivity_expiry < effective_expiry:
                        effective_expiry = inactivity_expiry

                # ----------------------------------------------------
                # Step 3: Evaluate Expiry Warnings
                # ----------------------------------------------------
                if (
                    effective_expiry
                    and app.status in ("active", "draft")
                    and now < effective_expiry
                ):
                    warnings_sent = list(app.governance_warnings_sent or [])
                    time_until_expiry = effective_expiry - now

                    for interval_days in warning_intervals:
                        if time_until_expiry <= timedelta(days=interval_days):
                            if interval_days not in warnings_sent:
                                warnings_sent.append(interval_days)
                                app.governance_warnings_sent = warnings_sent
                                app.updated_at = now

                                await self.audit_dal.record_event(
                                    action="app.expiry_warning_sent",
                                    outcome="success",
                                    organization_id=org.id,
                                    app_id=app.id,
                                    actor_user_id=None,
                                    actor_agent="governance-cycle",
                                    target_type="app",
                                    target_id=app.id,
                                    occurred_at=now,
                                    metadata={
                                        "warning_interval_days": interval_days,
                                        "expires_at": effective_expiry.isoformat(),
                                    },
                                )

                                # Send to owner if exists, else org admins
                                recipients = [app.owner.email] if app.owner and app.owner.email else [a.email for a in admins]
                                for r in recipients:
                                    await self.notifier.send(
                                        recipient=r,
                                        subject=f"Warning: Capsule '{app.name}' expires in {interval_days} days",
                                        template="expiry_warning",
                                        context={
                                            "app_name": app.name,
                                            "app_key": app.app_key,
                                            "days_left": interval_days,
                                            "deadline": effective_expiry.isoformat(),
                                        },
                                    )
                                stats["warnings_sent"] += 1

                # ----------------------------------------------------
                # Step 4: Transition Expired Apps to 'archived'
                # ----------------------------------------------------
                if (
                    effective_expiry
                    and now >= effective_expiry
                    and app.status not in ("archived", "deleting")
                ):
                    retention = app.purge_after_days or archive_retention_days
                    purge_deadline = now + timedelta(days=retention)
                    app.status = "archived"
                    app.governance_state = "archived"
                    app.archived_at = now
                    app.governance_deadline = purge_deadline
                    app.updated_at = now

                    await self.audit_dal.record_event(
                        action="app.archived",
                        outcome="success",
                        organization_id=org.id,
                        app_id=app.id,
                        actor_user_id=None,
                        actor_agent="governance-cycle",
                        target_type="app",
                        target_id=app.id,
                        occurred_at=now,
                        metadata={
                            "archived_at": now.isoformat(),
                            "purge_deadline": purge_deadline.isoformat(),
                            "retention_days": retention,
                            "reason": "Lifecycle expiry / inactivity limit reached",
                        },
                    )

                    recipients = [app.owner.email] if app.owner and app.owner.email else [a.email for a in admins]
                    for r in recipients:
                        await self.notifier.send(
                            recipient=r,
                            subject=f"App Archived: {app.name} has expired",
                            template="app_archived",
                            context={
                                "app_name": app.name,
                                "app_key": app.app_key,
                                "deadline": purge_deadline.isoformat(),
                            },
                        )
                    stats["archived_count"] += 1
                    continue

                # ----------------------------------------------------
                # Step 5: Purge Archived Apps past Retention Window
                # ----------------------------------------------------
                if (
                    app.status == "archived"
                    and app.governance_deadline
                    and now >= app.governance_deadline
                ):
                    app.status = "deleting"
                    app.governance_state = "purged"
                    app.updated_at = now

                    await self.audit_dal.record_event(
                        action="app.purged",
                        outcome="success",
                        organization_id=org.id,
                        app_id=app.id,
                        actor_user_id=None,
                        actor_agent="governance-cycle",
                        target_type="app",
                        target_id=app.id,
                        occurred_at=now,
                        metadata={
                            "purged_at": now.isoformat(),
                            "archived_at": app.archived_at.isoformat() if app.archived_at else None,
                        },
                    )

                    for admin in admins:
                        await self.notifier.send(
                            recipient=admin.email,
                            subject=f"App Purged: {app.name} retention window completed",
                            template="app_purged",
                            context={
                                "app_name": app.name,
                                "app_key": app.app_key,
                            },
                        )
                    stats["purged_count"] += 1

        await self.db.flush()
        return stats

    async def get_inventory(self, org_id: uuid.UUID) -> List[Dict[str, Any]]:
        """
        FR-036 Application Inventory listing.
        Returns every app with owner, status, user count, capabilities,
        last activity, version, and expiry status.
        """
        result = await self.db.execute(
            select(App)
            .options(
                selectinload(App.owner),
                selectinload(App.nominated_owner),
                selectinload(App.versions),
            )
            .where(App.organization_id == org_id)
            .order_by(App.created_at.desc())
        )
        apps = list(result.scalars().all())
        now = datetime.now(timezone.utc)
        inventory: List[Dict[str, Any]] = []

        for app in apps:
            # Calculate active distinct users
            shares_query = await self.db.execute(
                select(func.count(AppShare.user_id.distinct())).where(
                    and_(
                        AppShare.app_id == app.id,
                        AppShare.status == "active",
                        AppShare.user_id.is_not(None),
                    )
                )
            )
            shared_user_count = shares_query.scalar() or 0
            user_count = shared_user_count + (1 if app.owner_user_id else 0)

            # Capabilities & connectors
            manifest = dict(app.manifest or {})
            caps_dict = manifest.get("capabilities", {})
            capabilities_list = list(caps_dict.keys()) if isinstance(caps_dict, dict) else []

            connectors_list = []
            raw_connectors: List[Any] = []
            if isinstance(caps_dict, dict) and "connectors" in caps_dict:
                conn_val = caps_dict["connectors"]
                if isinstance(conn_val, dict):
                    raw_connectors.extend(conn_val.keys())
                elif isinstance(conn_val, list):
                    raw_connectors.extend(conn_val)
            if "connectors" in manifest and isinstance(manifest["connectors"], list):
                raw_connectors.extend(manifest["connectors"])

            for c in raw_connectors:
                if isinstance(c, str):
                    connectors_list.append(c)
                elif isinstance(c, dict):
                    connectors_list.append(str(c.get("type") or c.get("name") or c.get("id") or c))
                else:
                    connectors_list.append(str(c))

            # Expiry status calculation
            expiry_status = "active"
            if app.status == "archived":
                expiry_status = "archived"
            elif app.status == "suspended":
                if app.governance_state == "grace_period_expired":
                    expiry_status = "grace_period_expired"
                else:
                    expiry_status = "suspended"
            elif app.governance_state == "pending_owner":
                expiry_status = "pending_owner"
            elif app.expires_at:
                if now >= app.expires_at:
                    expiry_status = "expired"
                elif (app.expires_at - now).days <= 1:
                    expiry_status = "warning_1d"
                elif (app.expires_at - now).days <= 7:
                    expiry_status = "warning_7d"
                elif (app.expires_at - now).days <= 14:
                    expiry_status = "warning_14d"

            # Version info
            version_str = "v1"
            if app.versions:
                sorted_vers = sorted(app.versions, key=lambda v: v.version_number, reverse=True)
                version_str = f"v{sorted_vers[0].version_number}"

            inventory.append({
                "id": str(app.id),
                "app_key": app.app_key,
                "name": app.name,
                "description": app.description,
                "status": app.status,
                "governance_state": app.governance_state,
                "expiry_status": expiry_status,
                "owner": {
                    "id": str(app.owner.id),
                    "email": app.owner.email,
                    "display_name": app.owner.display_name or app.owner.email.split("@")[0],
                } if app.owner else None,
                "nominated_owner": {
                    "id": str(app.nominated_owner.id),
                    "email": app.nominated_owner.email,
                    "display_name": app.nominated_owner.display_name,
                } if app.nominated_owner else None,
                "user_count": user_count,
                "capabilities": capabilities_list,
                "connectors": connectors_list,
                "current_version": version_str,
                "last_activity_at": app.last_activity_at.isoformat() if app.last_activity_at else None,
                "expires_at": app.expires_at.isoformat() if app.expires_at else None,
                "governance_deadline": app.governance_deadline.isoformat() if app.governance_deadline else None,
                "created_at": app.created_at.isoformat() if app.created_at else None,
            })

        return inventory

    def export_inventory_csv(self, inventory: List[Dict[str, Any]]) -> str:
        """Export inventory items as RFC 4180 compliant CSV."""
        output = io.StringIO()
        fieldnames = [
            "id",
            "app_key",
            "name",
            "owner_email",
            "status",
            "governance_state",
            "expiry_status",
            "user_count",
            "capabilities",
            "connectors",
            "current_version",
            "last_activity_at",
            "expires_at",
            "governance_deadline",
            "created_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for item in inventory:
            owner_email = item["owner"]["email"] if item.get("owner") else "unowned"
            writer.writerow({
                "id": item["id"],
                "app_key": item["app_key"],
                "name": item["name"],
                "owner_email": owner_email,
                "status": item["status"],
                "governance_state": item["governance_state"],
                "expiry_status": item["expiry_status"],
                "user_count": item["user_count"],
                "capabilities": ";".join(item.get("capabilities", [])),
                "connectors": ";".join(item.get("connectors", [])),
                "current_version": item["current_version"],
                "last_activity_at": item["last_activity_at"] or "",
                "expires_at": item["expires_at"] or "",
                "governance_deadline": item["governance_deadline"] or "",
                "created_at": item["created_at"] or "",
            })

        return output.getvalue()
