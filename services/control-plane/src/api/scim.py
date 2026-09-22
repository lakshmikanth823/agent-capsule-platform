"""
SCIM 2.0 API (RFC 7643 & RFC 7644):
Users, Groups, ServiceProviderConfig, Schemas, and Token Rotation.
Implements instant deprovisioning cascades and real-time group-to-role sync.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.session import get_db_session
from db.models import Organization, User, SCIMGroup, OrganizationMember
from db.dal import (
    SCIMTokenDAL, SCIMGroupDAL, UserDAL, OrganizationDAL,
    GroupRoleMappingDAL, AppShareDAL
)
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from services.deprovisioning import deprovision_user
from services.group_sync import propagate_group_membership_changes

router = APIRouter(tags=["SCIM 2.0"])

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"


# ==========================================
# SCIM Bearer Token Authentication
# ==========================================

async def get_current_scim_org(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session),
) -> Organization:
    """Authenticates SCIM requests via per-organization rotated bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "schemas": [SCIM_ERROR_SCHEMA],
                "status": "401",
                "detail": "Missing or invalid SCIM Authorization bearer token.",
            },
        )

    raw_token = authorization[len("Bearer "):].strip()
    token_dal = SCIMTokenDAL(db)
    org = await token_dal.get_org_by_token(raw_token)

    if not org or org.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "schemas": [SCIM_ERROR_SCHEMA],
                "status": "401",
                "detail": "SCIM token is invalid, revoked, or organization is inactive.",
            },
        )
    return org


# ==========================================
# SCIM Token Management (Dashboard Endpoints)
# ==========================================

@router.post("/organizations/{org_id}/scim/rotate-token")
async def rotate_scim_token(
    org_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Rotates the SCIM 2.0 bearer token for the organization. Returns raw token once."""
    if user.organization_id != org_id or user.platform_role not in ["owner", "editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization administrators can rotate SCIM tokens."},
        )

    token_dal = SCIMTokenDAL(db)
    raw_token, record = await token_dal.rotate_token(org_id)
    await db.commit()

    return {
        "token": raw_token,
        "token_prefix": record.token_prefix,
        "status": record.status,
        "created_at": record.created_at.isoformat(),
        "scim_base_url": "http://localhost:8000/scim/v2",
    }


@router.get("/organizations/{org_id}/scim/token")
async def get_scim_token_info(
    org_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Returns active SCIM token metadata (prefix, created_at) without exposing the secret."""
    if user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    token_dal = SCIMTokenDAL(db)
    record = await token_dal.get_token_record(org_id)
    if not record:
        return {"configured": False}

    return {
        "configured": True,
        "token_prefix": record.token_prefix,
        "status": record.status,
        "created_at": record.created_at.isoformat(),
        "scim_base_url": "http://localhost:8000/scim/v2",
    }


# ==========================================
# RFC 7644 Discovery Endpoints
# ==========================================

@router.get("/scim/v2/ServiceProviderConfig")
async def get_service_provider_config():
    """RFC 7644 Section 3.2 ServiceProviderConfig specification."""
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "https://tools.ietf.org/html/rfc7644",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 100},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "name": "OAuth Bearer Token",
                "description": "Authentication using per-organization bearer tokens",
                "specUri": "https://tools.ietf.org/html/rfc6750",
                "type": "oauthbearertoken",
                "primary": True,
            }
        ],
    }


@router.get("/scim/v2/Schemas")
async def get_schemas():
    """Returns supported SCIM schemas."""
    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": 2,
        "Resources": [
            {
                "id": SCIM_USER_SCHEMA,
                "name": "User",
                "description": "User Account",
                "schema": SCIM_USER_SCHEMA,
            },
            {
                "id": SCIM_GROUP_SCHEMA,
                "name": "Group",
                "description": "Group",
                "schema": SCIM_GROUP_SCHEMA,
            },
        ],
    }


@router.get("/scim/v2/ResourceTypes")
async def get_resource_types():
    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": 2,
        "Resources": [
            {
                "id": "User",
                "name": "User",
                "endpoint": "/Users",
                "schema": SCIM_USER_SCHEMA,
            },
            {
                "id": "Group",
                "name": "Group",
                "endpoint": "/Groups",
                "schema": SCIM_GROUP_SCHEMA,
            },
        ],
    }


# ==========================================
# Helpers: Format User and Group SCIM JSON
# ==========================================

def _format_scim_user(user: User, org: Organization) -> Dict[str, Any]:
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "id": str(user.id),
        "userName": user.email,
        "name": {
            "formatted": user.display_name or user.email,
            "givenName": (user.display_name or "").split(" ")[0] if user.display_name else "",
            "familyName": " ".join((user.display_name or "").split(" ")[1:]) if user.display_name and " " in user.display_name else "",
        },
        "displayName": user.display_name or user.email,
        "emails": [
            {"value": user.email, "type": "work", "primary": True}
        ],
        "active": user.status == "active",
        "meta": {
            "resourceType": "User",
            "created": user.created_at.isoformat() if user.created_at else None,
            "lastModified": user.updated_at.isoformat() if user.updated_at else None,
            "location": f"/scim/v2/Users/{user.id}",
        },
    }


def _format_scim_group(group: SCIMGroup, members: List[User]) -> Dict[str, Any]:
    return {
        "schemas": [SCIM_GROUP_SCHEMA],
        "id": str(group.id),
        "displayName": group.display_name,
        "externalId": group.external_id,
        "members": [
            {
                "value": str(m.id),
                "display": m.email,
                "$ref": f"/scim/v2/Users/{m.id}",
            }
            for m in members
        ],
        "meta": {
            "resourceType": "Group",
            "created": group.created_at.isoformat() if group.created_at else None,
            "lastModified": group.updated_at.isoformat() if group.updated_at else None,
            "location": f"/scim/v2/Groups/{group.id}",
        },
    }


# ==========================================
# SCIM Users Endpoints
# ==========================================

@router.get("/scim/v2/Users")
async def list_scim_users(
    filter: Optional[str] = Query(None),
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=1, le=100),
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists SCIM users for the authenticated organization. Supports simple filters."""
    user_dal = UserDAL(db)
    email_filter = None
    if filter:
        # e.g. userName eq "alice@example.com"
        import re
        m = re.search(r'userName\s+eq\s+["\']([^"\']+)["\']', filter, re.IGNORECASE)
        if m:
            email_filter = m.group(1)

    users = await user_dal.list_users_for_org(org.id, email_filter=email_filter)
    paginated = users[startIndex - 1 : startIndex - 1 + count]

    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": len(users),
        "startIndex": startIndex,
        "itemsPerPage": len(paginated),
        "Resources": [_format_scim_user(u, org) for u in paginated],
    }


@router.get("/scim/v2/Users/{user_id}")
async def get_scim_user(
    user_id: uuid.UUID,
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves a single user by SCIM ID."""
    user_dal = UserDAL(db)
    user = await user_dal.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": f"User '{user_id}' not found."},
        )
    return _format_scim_user(user, org)


@router.post("/scim/v2/Users", status_code=status.HTTP_201_CREATED)
async def create_scim_user(
    body: Dict[str, Any],
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Provisions a new user in the organization via SCIM."""
    user_name = body.get("userName")
    emails = body.get("emails", [])
    email = user_name or (emails[0].get("value") if emails else None)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "400", "detail": "Missing userName or email."},
        )

    display_name = body.get("displayName")
    if not display_name and "name" in body:
        display_name = body["name"].get("formatted")

    user_dal = UserDAL(db)
    user = await user_dal.get_by_email(email)
    is_active = body.get("active", True)
    status_str = "active" if is_active else "deprovisioned"

    if not user:
        user = await user_dal.create(
            email=email,
            display_name=display_name or email.split("@")[0],
            identity_subject=body.get("externalId"),
            identity_issuer="scim",
            status=status_str,
        )
        await user_dal.add_to_org(org.id, user.id, platform_role="user", status=status_str)
    else:
        # Check org membership
        members = await user_dal.get_org_members(org.id)
        if not any(m.user_id == user.id for m in members):
            await user_dal.add_to_org(org.id, user.id, platform_role="user", status=status_str)
        else:
            await user_dal.set_status(user.id, status_str)
            await user_dal.update_org_member_status(org.id, user.id, status_str)

    await db.commit()
    return _format_scim_user(user, org)


@router.put("/scim/v2/Users/{user_id}")
async def update_scim_user(
    user_id: uuid.UUID,
    body: Dict[str, Any],
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Replaces user attributes. If active: false, executes instant deprovisioning cascade."""
    user_dal = UserDAL(db)
    user = await user_dal.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": f"User '{user_id}' not found."},
        )

    is_active = body.get("active", True)
    if not is_active:
        await deprovision_user(db, org.id, user_id, reason="SCIM PUT active=false")
        await db.commit()
        refreshed = await user_dal.get_by_id(user_id)
        return _format_scim_user(refreshed, org)

    display_name = body.get("displayName")
    if not display_name and "name" in body:
        display_name = body["name"].get("formatted")

    await user_dal.update_user(user_id, display_name=display_name)
    await user_dal.set_status(user_id, "active")
    await user_dal.update_org_member_status(org.id, user_id, "active")
    await db.commit()

    refreshed = await user_dal.get_by_id(user_id)
    return _format_scim_user(refreshed, org)


@router.patch("/scim/v2/Users/{user_id}")
async def patch_scim_user(
    user_id: uuid.UUID,
    body: Dict[str, Any],
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Applies RFC 7644 PATCH operations.
    Specifically detects active: false and triggers instant deprovisioning cascade.
    """
    user_dal = UserDAL(db)
    user = await user_dal.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": f"User '{user_id}' not found."},
        )

    operations = body.get("Operations", [])
    deactivate = False
    new_display_name = None

    for op in operations:
        op_type = op.get("op", "").lower()
        path = (op.get("path") or "").lower()
        val = op.get("value")

        if op_type in ["replace", "add"]:
            if path == "active" or (isinstance(val, dict) and "active" in val):
                active_val = val if path == "active" else val.get("active")
                if active_val is False or str(active_val).lower() == "false":
                    deactivate = True
            if path in ["displayname", "name.formatted"]:
                new_display_name = str(val)
            elif isinstance(val, dict) and "displayName" in val:
                new_display_name = val["displayName"]

    if deactivate:
        await deprovision_user(db, org.id, user_id, reason="SCIM PATCH active=false")
        await db.commit()
    else:
        if new_display_name is not None:
            await user_dal.update_user(user_id, display_name=new_display_name)
            await db.commit()

    refreshed = await user_dal.get_by_id(user_id)
    return _format_scim_user(refreshed, org)


@router.delete("/scim/v2/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scim_user(
    user_id: uuid.UUID,
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Deletes / deprovisions user and executes cascade."""
    user_dal = UserDAL(db)
    user = await user_dal.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": f"User '{user_id}' not found."},
        )

    await deprovision_user(db, org.id, user_id, reason="SCIM DELETE user")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==========================================
# SCIM Groups Endpoints
# ==========================================

@router.get("/scim/v2/Groups")
async def list_scim_groups(
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists SCIM groups and their members."""
    group_dal = SCIMGroupDAL(db)
    groups = await group_dal.list_for_org(org.id)
    resources = []
    for g in groups:
        members = await group_dal.get_members(g.id)
        resources.append(_format_scim_group(g, members))

    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": len(groups),
        "Resources": resources,
    }


@router.get("/scim/v2/Groups/{group_id}")
async def get_scim_group(
    group_id: uuid.UUID,
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves a single SCIM group."""
    group_dal = SCIMGroupDAL(db)
    group = await group_dal.get_by_id(group_id)
    if not group or group.organization_id != org.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": f"Group '{group_id}' not found."},
        )
    members = await group_dal.get_members(group.id)
    return _format_scim_group(group, members)


@router.post("/scim/v2/Groups", status_code=status.HTTP_201_CREATED)
async def create_scim_group(
    body: Dict[str, Any],
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Creates a new SCIM directory group and syncs initial members."""
    display_name = body.get("displayName")
    if not display_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "400", "detail": "Missing displayName."},
        )

    group_dal = SCIMGroupDAL(db)
    existing = await group_dal.get_by_name(org.id, display_name)
    if existing:
        group = existing
    else:
        group = await group_dal.create_group(
            org_id=org.id,
            display_name=display_name,
            external_id=body.get("externalId"),
        )

    # Sync initial members if provided
    raw_members = body.get("members", [])
    target_user_ids = []
    for m in raw_members:
        u_val = m.get("value")
        if u_val:
            try:
                target_user_ids.append(uuid.UUID(u_val))
            except ValueError:
                pass

    if target_user_ids:
        added, removed = await group_dal.set_members(group.id, target_user_ids)
        await propagate_group_membership_changes(db, org.id, group.id, added, removed)

    await db.commit()
    members = await group_dal.get_members(group.id)
    return _format_scim_group(group, members)


@router.put("/scim/v2/Groups/{group_id}")
async def put_scim_group(
    group_id: uuid.UUID,
    body: Dict[str, Any],
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Replaces SCIM group members and updates app role assignments."""
    group_dal = SCIMGroupDAL(db)
    group = await group_dal.get_by_id(group_id)
    if not group or group.organization_id != org.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": f"Group '{group_id}' not found."},
        )

    display_name = body.get("displayName")
    if display_name:
        await group_dal.update_group(group_id, display_name=display_name)

    raw_members = body.get("members", [])
    target_user_ids = []
    for m in raw_members:
        u_val = m.get("value")
        if u_val:
            try:
                target_user_ids.append(uuid.UUID(u_val))
            except ValueError:
                pass

    added, removed = await group_dal.set_members(group.id, target_user_ids)
    await propagate_group_membership_changes(db, org.id, group.id, added, removed)
    await db.commit()

    members = await group_dal.get_members(group.id)
    return _format_scim_group(group, members)


@router.patch("/scim/v2/Groups/{group_id}")
async def patch_scim_group(
    group_id: uuid.UUID,
    body: Dict[str, Any],
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Applies member additions and removals to SCIM group and propagates roles within seconds."""
    group_dal = SCIMGroupDAL(db)
    group = await group_dal.get_by_id(group_id)
    if not group or group.organization_id != org.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": f"Group '{group_id}' not found."},
        )

    operations = body.get("Operations", [])
    added_ids: List[uuid.UUID] = []
    removed_ids: List[uuid.UUID] = []

    for op in operations:
        op_type = op.get("op", "").lower()
        path = (op.get("path") or "").lower()
        val = op.get("value")

        if op_type == "add":
            members_to_add = val if isinstance(val, list) else ([val] if isinstance(val, dict) else [])
            for m in members_to_add:
                u_val = m.get("value") if isinstance(m, dict) else m
                if u_val:
                    try:
                        uid = uuid.UUID(str(u_val))
                        if await group_dal.add_member(group.id, uid):
                            added_ids.append(uid)
                    except ValueError:
                        pass

        elif op_type == "remove":
            if "members" in path and "value eq" in path:
                # e.g. path="members[value eq \"usr_123\"]"
                import re
                m = re.search(r'value\s+eq\s+["\']([^"\']+)["\']', path, re.IGNORECASE)
                if m:
                    try:
                        uid = uuid.UUID(m.group(1))
                        if await group_dal.remove_member(group.id, uid):
                            removed_ids.append(uid)
                    except ValueError:
                        pass
            elif isinstance(val, list):
                for m in val:
                    u_val = m.get("value") if isinstance(m, dict) else m
                    if u_val:
                        try:
                            uid = uuid.UUID(str(u_val))
                            if await group_dal.remove_member(group.id, uid):
                                removed_ids.append(uid)
                        except ValueError:
                            pass

    await propagate_group_membership_changes(db, org.id, group.id, added_ids, removed_ids)
    await db.commit()

    members = await group_dal.get_members(group.id)
    return _format_scim_group(group, members)


@router.delete("/scim/v2/Groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scim_group(
    group_id: uuid.UUID,
    org: Organization = Depends(get_current_scim_org),
    db: AsyncSession = Depends(get_db_session),
):
    """Deletes SCIM group and revokes associated AppShares."""
    group_dal = SCIMGroupDAL(db)
    group = await group_dal.get_by_id(group_id)
    if not group or group.organization_id != org.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": f"Group '{group_id}' not found."},
        )

    current_members = await group_dal.get_members(group.id)
    member_ids = [m.id for m in current_members]
    await propagate_group_membership_changes(db, org.id, group.id, added_user_ids=[], removed_user_ids=member_ids)
    await group_dal.delete_group(group.id)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
