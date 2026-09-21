"""
Sharing and Roles API Endpoints

Implements PRD, TRD Sections 15 & 17, and API/CLI spec:
- Platform roles: Owner, Editor, User.
- Application roles declared in manifest, assigned to users or groups.
- Endpoints: share (POST), unshare/revoke (DELETE), list shares (GET), evaluate access (GET).
- Strict role authorization: Only Owner and Editor can assign or modify shares.
- Writes audit events for every mutation.
"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import AppDAL, AppShareDAL, UserDAL, AuditDAL
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser

router = APIRouter(tags=["Sharing"])


class CreateShareRequest(BaseModel):
    user_email: Optional[str] = Field(None, description="Email of user to share with")
    user_id: Optional[str] = Field(None, description="User UUID to share with")
    group_name: Optional[str] = Field(None, description="Group name for group-based sharing")
    app_role: str = Field(..., description="Application role declared in manifest (e.g. employee, manager)")
    expires_at: Optional[datetime] = Field(None, description="Optional share expiration timestamp")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class AppShareResponse(BaseModel):
    id: str
    app_id: str
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    group_name: Optional[str] = None
    grant_type: str
    app_role: str
    status: str
    granted_by_user_id: Optional[str] = None
    granted_at: datetime
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ShareListResponse(BaseModel):
    shares: List[AppShareResponse]
    default_scope: str = "org"
    external_users_allowed: bool = False


class AccessEvaluationResponse(BaseModel):
    allowed: bool
    platform_role: str
    app_roles: List[str]
    reason: Optional[str] = None


def check_management_permission(app: Any, current_user: AuthenticatedUser) -> None:
    """
    Enforce that only Owner and Editor can create, modify, or revoke shares.
    Regular User role is blocked with 403 Forbidden.
    """
    is_app_owner = app.owner_user_id and app.owner_user_id == current_user.id
    is_platform_manager = current_user.platform_role in ("owner", "editor")

    if not (is_app_owner or is_platform_manager):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only Owner and Editor can manage sharing assignments.",
        )


@router.get("/v1/apps/{app_id}/shares", response_model=ShareListResponse)
@router.get("/apps/{app_id}/shares", response_model=ShareListResponse)
async def list_app_shares(
    app_id: str,
    include_revoked: bool = Query(True, description="Include revoked shares"),
    db: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    app_dal = AppDAL(db)
    share_dal = AppShareDAL(db)
    user_dal = UserDAL(db)

    app = await app_dal.get_by_id_or_key(current_user.organization_id, app_id)
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")

    shares = await share_dal.list_shares_for_app(app.id, include_revoked=include_revoked)
    policy = await share_dal.get_share_policy(app.id)

    results: List[AppShareResponse] = []
    for s in shares:
        user_email = None
        if s.user_id:
            u = await user_dal.get_by_id(s.user_id)
            if u:
                user_email = u.email

        grant_type = s.metadata_.get("grant_type", "user" if s.user_id else "group")
        group_name = s.metadata_.get("group_name")

        results.append(
            AppShareResponse(
                id=str(s.id),
                app_id=str(s.app_id),
                user_id=str(s.user_id) if s.user_id else None,
                user_email=user_email,
                group_name=group_name,
                grant_type=grant_type,
                app_role=s.app_role or "employee",
                status=s.status,
                granted_by_user_id=str(s.granted_by_user_id) if s.granted_by_user_id else None,
                granted_at=s.granted_at,
                expires_at=s.expires_at,
                metadata=s.metadata_ or {},
            )
        )

    return ShareListResponse(
        shares=results,
        default_scope=policy.default_scope if policy else "org",
        external_users_allowed=policy.external_users_allowed if policy else False,
    )


@router.post("/v1/apps/{app_id}/shares", response_model=AppShareResponse, status_code=status.HTTP_201_CREATED)
@router.post("/apps/{app_id}/shares", response_model=AppShareResponse, status_code=status.HTTP_201_CREATED)
async def create_app_share(
    app_id: str,
    payload: CreateShareRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    app_dal = AppDAL(db)
    share_dal = AppShareDAL(db)
    user_dal = UserDAL(db)
    audit_dal = AuditDAL(db)

    app = await app_dal.get_by_id_or_key(current_user.organization_id, app_id)
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")

    # 1. Authorization check: Only Owner and Editor can assign shares
    check_management_permission(app, current_user)

    # 2. Validate application role against manifest
    declared_roles: List[str] = []
    if app.manifest and isinstance(app.manifest, dict):
        declared_roles = app.manifest.get("roles", [])

    if declared_roles and payload.app_role not in declared_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role '{payload.app_role}' is not declared in app manifest. Available roles: {declared_roles}",
        )

    # 3. Resolve target user or group
    target_user_id: Optional[uuid.UUID] = None
    grant_type = "user"
    metadata = dict(payload.metadata or {})

    if payload.group_name:
        grant_type = "group"
        metadata["group_name"] = payload.group_name
        metadata["grant_type"] = "group"
    elif payload.user_id:
        try:
            target_user_id = uuid.UUID(payload.user_id)
            metadata["grant_type"] = "user"
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id format")
    elif payload.user_email:
        metadata["grant_type"] = "user"
        metadata["user_email"] = payload.user_email
        target_user = await user_dal.get_by_email(payload.user_email)
        if target_user:
            target_user_id = target_user.id
        else:
            # Create user in caller's organization
            target_user = await user_dal.create(
                email=payload.user_email,
                display_name=payload.user_email.split("@")[0],
            )
            await user_dal.add_to_org(
                organization_id=current_user.organization_id,
                user_id=target_user.id,
                platform_role="user",
            )
            target_user_id = target_user.id
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must specify at least one of user_email, user_id, or group_name",
        )

    # 4. Check if share already exists (idempotent share)
    if target_user_id:
        existing_shares = await share_dal.find_active_shares_for_user(app.id, target_user_id)
        matching = next((s for s in existing_shares if s.app_role == payload.app_role), None)
        if matching:
            return AppShareResponse(
                id=str(matching.id),
                app_id=str(matching.app_id),
                user_id=str(matching.user_id) if matching.user_id else None,
                user_email=payload.user_email,
                group_name=payload.group_name,
                grant_type=grant_type,
                app_role=matching.app_role or "employee",
                status=matching.status,
                granted_by_user_id=str(matching.granted_by_user_id) if matching.granted_by_user_id else None,
                granted_at=matching.granted_at,
                expires_at=matching.expires_at,
                metadata=matching.metadata_ or {},
            )

    # 5. Create or update share
    share = await share_dal.create_share(
        app_id=app.id,
        user_id=target_user_id,
        app_role=payload.app_role,
        status="active",
        granted_by_user_id=current_user.id,
        expires_at=payload.expires_at,
        metadata=metadata,
    )

    # 6. Write audit event
    await audit_dal.record_event(
        action="app.share.create",
        outcome="success",
        organization_id=app.organization_id,
        app_id=app.id,
        actor_user_id=current_user.id,
        target_type="app_share",
        target_id=share.id,
        metadata={
            "app_role": payload.app_role,
            "target_user_id": str(target_user_id) if target_user_id else None,
            "group_name": payload.group_name,
            "grant_type": grant_type,
        },
    )
    await db.commit()

    return AppShareResponse(
        id=str(share.id),
        app_id=str(share.app_id),
        user_id=str(share.user_id) if share.user_id else None,
        user_email=payload.user_email,
        group_name=payload.group_name,
        grant_type=grant_type,
        app_role=share.app_role or "employee",
        status=share.status,
        granted_by_user_id=str(share.granted_by_user_id) if share.granted_by_user_id else None,
        granted_at=share.granted_at,
        expires_at=share.expires_at,
        metadata=share.metadata_ or {},
    )


@router.delete("/v1/apps/{app_id}/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
@router.delete("/apps/{app_id}/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_app_share(
    app_id: str,
    share_id: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    app_dal = AppDAL(db)
    share_dal = AppShareDAL(db)
    audit_dal = AuditDAL(db)

    app = await app_dal.get_by_id_or_key(current_user.organization_id, app_id)
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")

    # 1. Authorization check: Only Owner and Editor can revoke shares
    check_management_permission(app, current_user)

    try:
        share_uuid = uuid.UUID(share_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid share_id format")

    share = await share_dal.get_share(share_uuid)
    if not share or share.app_id != app.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")

    # 2. Mark share as revoked
    await share_dal.revoke_share(share_uuid)

    # 3. Write audit event
    await audit_dal.record_event(
        action="app.share.revoke",
        outcome="success",
        organization_id=app.organization_id,
        app_id=app.id,
        actor_user_id=current_user.id,
        target_type="app_share",
        target_id=share.id,
        metadata={
            "app_role": share.app_role,
            "target_user_id": str(share.user_id) if share.user_id else None,
        },
    )


@router.get("/v1/apps/{app_id}/access", response_model=AccessEvaluationResponse)
@router.get("/apps/{app_id}/access", response_model=AccessEvaluationResponse)
async def evaluate_app_access(
    app_id: str,
    user_id: Optional[str] = Query(None, description="User UUID to evaluate"),
    email: Optional[str] = Query(None, description="User email to evaluate"),
    groups: Optional[str] = Query(None, description="Comma-separated group names"),
    org_id: Optional[str] = Query(None, description="User org ID"),
    db: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    app_dal = AppDAL(db)
    share_dal = AppShareDAL(db)
    user_dal = UserDAL(db)

    # Target user to evaluate (default to caller)
    target_user_id = uuid.UUID(user_id) if user_id else current_user.id
    target_org_id = uuid.UUID(org_id) if org_id else current_user.organization_id
    target_groups = [g.strip() for g in groups.split(",")] if groups else current_user.claims.get("groups", [])

    # Find app in target org or caller org
    app = await app_dal.get_by_id_or_key(target_org_id, app_id)
    if not app:
        # Try caller org
        app = await app_dal.get_by_id_or_key(current_user.organization_id, app_id)

    if not app:
        return AccessEvaluationResponse(
            allowed=False,
            platform_role="user",
            app_roles=[],
            reason="Capsule not found.",
        )

    if app.status not in ("active", "draft"):
        return AccessEvaluationResponse(
            allowed=False,
            platform_role="user",
            app_roles=[],
            reason=f"Capsule is {app.status}.",
        )

    # Cross-org check
    if app.organization_id != target_org_id:
        return AccessEvaluationResponse(
            allowed=False,
            platform_role="user",
            app_roles=[],
            reason="User belongs to a different organization.",
        )

    # Manifest declared roles
    declared_roles: List[str] = []
    if app.manifest and isinstance(app.manifest, dict):
        declared_roles = app.manifest.get("roles", [])

    # 1. Owner check
    if app.owner_user_id and app.owner_user_id == target_user_id:
        return AccessEvaluationResponse(
            allowed=True,
            platform_role="owner",
            app_roles=declared_roles if declared_roles else ["admin"],
        )

    # 2. Check user-specific shares
    user_shares = await share_dal.find_active_shares_for_user(app.id, target_user_id)
    now = datetime.utcnow()
    valid_user_shares = [
        s for s in user_shares
        if s.status == "active" and (s.expires_at is None or s.expires_at > now)
    ]
    if valid_user_shares:
        roles = [s.app_role for s in valid_user_shares if s.app_role]
        return AccessEvaluationResponse(
            allowed=True,
            platform_role="user",
            app_roles=roles if roles else ["employee"],
        )

    # 3. Check group shares
    all_shares = await share_dal.list_shares_for_app(app.id, include_revoked=False)
    matched_group_roles: List[str] = []
    for s in all_shares:
        if s.status == "active" and (s.expires_at is None or s.expires_at > now):
            group_name = s.metadata_.get("group_name")
            if group_name and group_name in target_groups:
                if s.app_role:
                    matched_group_roles.append(s.app_role)

    if matched_group_roles:
        return AccessEvaluationResponse(
            allowed=True,
            platform_role="user",
            app_roles=matched_group_roles,
        )

    # 4. Check org-wide default policy
    policy = await share_dal.get_share_policy(app.id)
    default_scope = policy.default_scope if policy else "org"
    if default_scope == "org" and app.organization_id == target_org_id:
        default_role = declared_roles[0] if declared_roles else "employee"
        return AccessEvaluationResponse(
            allowed=True,
            platform_role="user",
            app_roles=[default_role],
        )

    return AccessEvaluationResponse(
        allowed=False,
        platform_role="user",
        app_roles=[],
        reason="No active share or permission found.",
    )
