"""
Emergency Controls & Kill Switch API (Prompt 23)

Implements:
- App-level suspension & resume with required reason.
- Organization-level freeze & resume (suspends all sandboxes, blocks egress).
- Organization-wide connector disabling.
- Mass revocation of publish tokens and user sessions (org and user scope).
- Platform-operator break-glass emergency controls.
- Comprehensive audit event generation for all actions.
"""
import os
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import AppDAL, OrganizationDAL, UserDAL, AuditDAL
from auth.dependencies import get_current_user, get_current_user_no_org_check
from auth.models import AuthenticatedUser

router = APIRouter(prefix="/kill-switch", tags=["Kill Switch & Emergency Controls"])

DEFAULT_OPERATOR_SECRET = "dev-operator-break-glass-secret-key"


class SuspendRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Required explanation for the suspension")


class DisableConnectorRequest(BaseModel):
    reason: Optional[str] = Field(None, description="Optional explanation for disabling the connector")


def verify_platform_operator(
    x_platform_operator_key: Optional[str] = Header(None),
) -> str:
    expected_key = os.environ.get("PLATFORM_OPERATOR_SECRET", DEFAULT_OPERATOR_SECRET)
    if not x_platform_operator_key or x_platform_operator_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OPERATOR_AUTH_FAILED",
                "message": "Invalid or missing platform operator break-glass key.",
            },
        )
    return x_platform_operator_key


# ============================================================================
# 1. APP-LEVEL KILL SWITCH
# ============================================================================

@router.post("/apps/{app_id}/suspend")
async def suspend_app(
    app_id: str,
    payload: SuspendRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Instantly suspend a single capsule.
    Authorized for: Capsule Owner, Editor, or Organization Admin.
    Requires a valid reason.
    """
    app_dal = AppDAL(db)
    audit_dal = AuditDAL(db)

    app = await app_dal.get_by_id_or_key(current_user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    # Auth check: must be app owner, org owner, or org editor
    is_app_owner = app.owner_user_id == current_user.id
    is_org_manager = current_user.platform_role in ("owner", "editor")
    if not (is_app_owner or is_org_manager):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only the app owner, editor, or organization admin can suspend this app.",
            },
        )

    suspended_app = await app_dal.suspend(app.id, current_user.id, payload.reason)
    await audit_dal.record_event(
        action="app.suspend",
        outcome="success",
        actor_user_id=current_user.id,
        organization_id=app.organization_id,
        app_id=app.id,
        target_type="app",
        metadata={
            "app_key": app.app_key,
            "reason": payload.reason,
            "scope": "app",
            "actor_role": current_user.platform_role,
        },
    )

    return {
        "id": str(suspended_app.id),
        "app_key": suspended_app.app_key,
        "status": suspended_app.status,
        "suspended_at": suspended_app.suspended_at.isoformat() if suspended_app.suspended_at else None,
        "suspension_reason": suspended_app.suspension_reason,
        "message": f"Capsule '{app.app_key}' suspended successfully.",
    }


@router.post("/apps/{app_id}/resume")
async def resume_app(
    app_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user_no_org_check),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Resume a suspended capsule.
    Admin only: must be org owner, org editor, or app owner.
    """
    app_dal = AppDAL(db)
    audit_dal = AuditDAL(db)

    app = await app_dal.get_by_id_or_key(current_user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    is_app_owner = app.owner_user_id == current_user.id
    is_org_manager = current_user.platform_role in ("owner", "editor")
    if not (is_app_owner or is_org_manager):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only an administrator or app owner can resume this app.",
            },
        )

    resumed_app = await app_dal.resume(app.id, current_user.id)
    await audit_dal.record_event(
        action="app.resume",
        outcome="success",
        actor_user_id=current_user.id,
        organization_id=app.organization_id,
        app_id=app.id,
        target_type="app",
        metadata={
            "app_key": app.app_key,
            "scope": "app",
            "actor_role": current_user.platform_role,
        },
    )

    return {
        "id": str(resumed_app.id),
        "app_key": resumed_app.app_key,
        "status": resumed_app.status,
        "message": f"Capsule '{app.app_key}' resumed successfully.",
    }


# ============================================================================
# 2. ORGANIZATION-LEVEL FREEZE & RESUME
# ============================================================================

@router.post("/organizations/{org_id}/suspend")
async def freeze_organization(
    org_id: str,
    payload: SuspendRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Freeze an entire organization:
    - Suspends all apps and running sandboxes.
    - Blocks all egress.
    - Edge proxy returns clear suspended page.
    Org admin (owner) only.
    """
    if current_user.platform_role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only an organization owner/admin can freeze an organization.",
            },
        )

    org_dal = OrganizationDAL(db)
    app_dal = AppDAL(db)
    audit_dal = AuditDAL(db)

    try:
        val_uuid = uuid.UUID(org_id)
        org = await org_dal.get_by_id(val_uuid)
    except ValueError:
        org = await org_dal.get_by_slug(org_id)

    if not org or org.id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_id}' not found."},
        )

    # 1. Suspend organization
    suspended_org = await org_dal.suspend(org.id, current_user.id, payload.reason)

    # 2. Suspend all active apps for the organization
    suspended_apps = await app_dal.suspend_all_for_org(org.id, current_user.id, payload.reason)

    # 3. Audit log
    await audit_dal.record_event(
        action="organization.freeze",
        outcome="success",
        actor_user_id=current_user.id,
        organization_id=org.id,
        target_type="organization",
        metadata={
            "reason": payload.reason,
            "scope": "organization",
            "suspended_apps_count": len(suspended_apps),
        },
    )

    return {
        "id": str(suspended_org.id),
        "slug": suspended_org.slug,
        "status": suspended_org.status,
        "suspended_at": suspended_org.suspended_at.isoformat() if suspended_org.suspended_at else None,
        "suspension_reason": suspended_org.suspension_reason,
        "suspended_apps_count": len(suspended_apps),
        "message": f"Organization '{suspended_org.slug}' and {len(suspended_apps)} apps frozen successfully.",
    }


@router.post("/organizations/{org_id}/resume")
async def resume_organization(
    org_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user_no_org_check),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Resume a frozen organization.
    Org admin (owner) only.
    """
    if current_user.platform_role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only an organization owner/admin can resume an organization.",
            },
        )

    org_dal = OrganizationDAL(db)
    audit_dal = AuditDAL(db)

    try:
        val_uuid = uuid.UUID(org_id)
        org = await org_dal.get_by_id(val_uuid)
    except ValueError:
        org = await org_dal.get_by_slug(org_id)

    if not org or org.id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_id}' not found."},
        )

    resumed_org = await org_dal.resume(org.id, current_user.id)
    await audit_dal.record_event(
        action="organization.resume",
        outcome="success",
        actor_user_id=current_user.id,
        organization_id=org.id,
        target_type="organization",
        metadata={"scope": "organization"},
    )

    return {
        "id": str(resumed_org.id),
        "slug": resumed_org.slug,
        "status": resumed_org.status,
        "message": f"Organization '{resumed_org.slug}' resumed successfully.",
    }


# ============================================================================
# 3. CONNECTOR DISABLEMENT (ORGANIZATION-WIDE)
# ============================================================================

@router.post("/organizations/{org_id}/connectors/{connector_name}/disable")
async def disable_connector_org_wide(
    org_id: str,
    connector_name: str,
    payload: DisableConnectorRequest = DisableConnectorRequest(),
    current_user: AuthenticatedUser = Depends(get_current_user_no_org_check),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Disable a connector organization-wide.
    Org admin (owner or editor) only.
    """
    if current_user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization admins can disable connectors."},
        )

    org_dal = OrganizationDAL(db)
    audit_dal = AuditDAL(db)

    try:
        val_uuid = uuid.UUID(org_id)
        org = await org_dal.get_by_id(val_uuid)
    except ValueError:
        org = await org_dal.get_by_slug(org_id)

    if not org or org.id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_id}' not found."},
        )

    updated_org = await org_dal.disable_connector(org.id, connector_name, payload.reason)
    await audit_dal.record_event(
        action="connector.disable",
        outcome="success",
        actor_user_id=current_user.id,
        organization_id=org.id,
        target_type="connector",
        metadata={
            "connector": connector_name,
            "reason": payload.reason,
            "scope": "organization",
        },
    )

    return {
        "organization_id": str(updated_org.id),
        "connector": connector_name,
        "disabled": True,
        "disabled_connectors": updated_org.environment_profile.get("disabled_connectors", []),
        "message": f"Connector '{connector_name}' disabled organization-wide.",
    }


# ============================================================================
# 4. MASS REVOCATION (TOKENS & SESSIONS)
# ============================================================================

@router.post("/organizations/{org_id}/tokens/revoke")
async def mass_revoke_org_tokens(
    org_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user_no_org_check),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Mass revoke all publish tokens for an entire organization.
    Org admin (owner/editor) only.
    """
    if current_user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization admins can revoke tokens."},
        )

    org_dal = OrganizationDAL(db)
    audit_dal = AuditDAL(db)

    try:
        val_uuid = uuid.UUID(org_id)
        org = await org_dal.get_by_id(val_uuid)
    except ValueError:
        org = await org_dal.get_by_slug(org_id)

    if not org or org.id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_id}' not found."},
        )

    revoked_at = await org_dal.revoke_tokens(org.id)
    await audit_dal.record_event(
        action="tokens.revoke_org",
        outcome="success",
        actor_user_id=current_user.id,
        organization_id=org.id,
        target_type="organization",
        metadata={"scope": "organization", "revoked_at": revoked_at.isoformat()},
    )

    return {
        "organization_id": str(org.id),
        "tokens_revoked_at": revoked_at.isoformat(),
        "message": f"All publish tokens for organization '{org.slug}' have been revoked.",
    }


@router.post("/organizations/{org_id}/sessions/revoke")
async def mass_revoke_org_sessions(
    org_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user_no_org_check),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Mass revoke all user sessions for an entire organization.
    Org admin (owner/editor) only.
    """
    if current_user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization admins can revoke sessions."},
        )

    org_dal = OrganizationDAL(db)
    audit_dal = AuditDAL(db)

    try:
        val_uuid = uuid.UUID(org_id)
        org = await org_dal.get_by_id(val_uuid)
    except ValueError:
        org = await org_dal.get_by_slug(org_id)

    if not org or org.id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_id}' not found."},
        )

    revoked_at = await org_dal.revoke_sessions(org.id)
    await audit_dal.record_event(
        action="sessions.revoke_org",
        outcome="success",
        actor_user_id=current_user.id,
        organization_id=org.id,
        target_type="organization",
        metadata={"scope": "organization", "revoked_at": revoked_at.isoformat()},
    )

    return {
        "organization_id": str(org.id),
        "sessions_revoked_at": revoked_at.isoformat(),
        "message": f"All user sessions for organization '{org.slug}' have been revoked.",
    }


@router.post("/users/{user_id}/tokens/revoke")
async def mass_revoke_user_tokens(
    user_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user_no_org_check),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Mass revoke all publish tokens for a specific user.
    Permitted for: the user themselves or an Org admin.
    """
    user_dal = UserDAL(db)
    audit_dal = AuditDAL(db)

    target_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    is_self = current_user.id == target_uuid
    is_org_admin = current_user.platform_role in ("owner", "editor")

    if not (is_self or is_org_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Cannot revoke tokens for another user."},
        )

    revoked_at = await user_dal.revoke_tokens(target_uuid)
    await audit_dal.record_event(
        action="tokens.revoke_user",
        outcome="success",
        actor_user_id=current_user.id,
        organization_id=current_user.organization_id,
        target_type="user",
        metadata={"target_user_id": str(target_uuid), "revoked_at": revoked_at.isoformat()},
    )

    return {
        "user_id": str(target_uuid),
        "tokens_revoked_at": revoked_at.isoformat(),
        "message": f"All publish tokens for user '{target_uuid}' have been revoked.",
    }


@router.post("/users/{user_id}/sessions/revoke")
async def mass_revoke_user_sessions(
    user_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user_no_org_check),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Mass revoke all sessions for a specific user.
    Permitted for: the user themselves or an Org admin.
    """
    user_dal = UserDAL(db)
    audit_dal = AuditDAL(db)

    target_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    is_self = current_user.id == target_uuid
    is_org_admin = current_user.platform_role in ("owner", "editor")

    if not (is_self or is_org_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Cannot revoke sessions for another user."},
        )

    revoked_at = await user_dal.revoke_sessions(target_uuid)
    await audit_dal.record_event(
        action="sessions.revoke_user",
        outcome="success",
        actor_user_id=current_user.id,
        organization_id=current_user.organization_id,
        target_type="user",
        metadata={"target_user_id": str(target_uuid), "revoked_at": revoked_at.isoformat()},
    )

    return {
        "user_id": str(target_uuid),
        "sessions_revoked_at": revoked_at.isoformat(),
        "message": f"All sessions for user '{target_uuid}' have been revoked.",
    }


# ============================================================================
# 5. PLATFORM-OPERATOR BREAK-GLASS EMERGENCY CONTROLS
# ============================================================================

@router.post("/operator/freeze-org/{org_id}")
async def operator_freeze_org(
    org_id: str,
    payload: SuspendRequest,
    operator_key: str = Depends(verify_platform_operator),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Platform-operator break-glass: freeze any organization across the platform.
    """
    org_dal = OrganizationDAL(db)
    app_dal = AppDAL(db)
    audit_dal = AuditDAL(db)

    try:
        val_uuid = uuid.UUID(org_id)
        org = await org_dal.get_by_id(val_uuid)
    except ValueError:
        org = await org_dal.get_by_slug(org_id)

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_id}' not found."},
        )

    suspended_org = await org_dal.suspend(org.id, None, f"[BREAK-GLASS OPERATOR] {payload.reason}")
    suspended_apps = await app_dal.suspend_all_for_org(org.id, None, f"[BREAK-GLASS OPERATOR] {payload.reason}")

    await audit_dal.record_event(
        action="operator.freeze_org",
        outcome="success",
        organization_id=org.id,
        target_type="organization",
        metadata={
            "reason": payload.reason,
            "scope": "platform-operator",
            "suspended_apps_count": len(suspended_apps),
        },
    )

    return {
        "id": str(suspended_org.id),
        "slug": suspended_org.slug,
        "status": suspended_org.status,
        "suspended_apps_count": len(suspended_apps),
        "message": f"[OPERATOR] Organization '{suspended_org.slug}' frozen via break-glass.",
    }


@router.post("/operator/global-freeze")
async def operator_global_freeze(
    payload: SuspendRequest,
    operator_key: str = Depends(verify_platform_operator),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Platform-operator break-glass: emergency freeze all organizations and apps platform-wide.
    """
    org_dal = OrganizationDAL(db)
    app_dal = AppDAL(db)
    audit_dal = AuditDAL(db)

    orgs = await org_dal.list_all()
    total_suspended_apps = 0

    for org in orgs:
        await org_dal.suspend(org.id, None, f"[GLOBAL BREAK-GLASS] {payload.reason}")
        apps = await app_dal.suspend_all_for_org(org.id, None, f"[GLOBAL BREAK-GLASS] {payload.reason}")
        total_suspended_apps += len(apps)

    await audit_dal.record_event(
        action="operator.global_freeze",
        outcome="success",
        target_type="platform",
        metadata={
            "reason": payload.reason,
            "scope": "platform",
            "organizations_frozen": len(orgs),
            "apps_suspended": total_suspended_apps,
        },
    )

    return {
        "status": "frozen",
        "organizations_frozen": len(orgs),
        "apps_suspended": total_suspended_apps,
        "message": "[OPERATOR] Global emergency platform freeze executed.",
    }
