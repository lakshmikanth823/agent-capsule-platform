"""
Group-to-Role Mapping API: Manage mapping between SCIM directory groups and Capsule application roles.
"""
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import GroupRoleMappingDAL, SCIMGroupDAL, AppDAL
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from services.group_sync import propagate_new_role_mapping

router = APIRouter(tags=["Group Role Mappings"])


class CreateGroupRoleMappingRequest(BaseModel):
    group_id: uuid.UUID = Field(..., description="SCIM Group ID")
    app_id: uuid.UUID = Field(..., description="Target Application ID")
    app_role: str = Field(..., description="Role to grant in the app (e.g. editor, viewer, admin)")


class GroupRoleMappingResponse(BaseModel):
    id: str
    organization_id: str
    group_id: str
    group_name: str
    app_id: str
    app_key: str
    app_role: str
    created_at: str


@router.post("/organizations/{org_id}/group-role-mappings", response_model=GroupRoleMappingResponse, status_code=status.HTTP_201_CREATED)
async def create_group_role_mapping(
    org_id: uuid.UUID,
    body: CreateGroupRoleMappingRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Creates a new group-to-app-role mapping and immediately propagates roles to current group members."""
    if user.organization_id != org_id or user.platform_role not in ["owner", "editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization administrators can configure group role mappings."},
        )

    group_dal = SCIMGroupDAL(db)
    group = await group_dal.get_by_id(body.group_id)
    if not group or group.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "GROUP_NOT_FOUND", "message": f"SCIM group '{body.group_id}' not found."},
        )

    app_dal = AppDAL(db)
    app = await app_dal.get_by_id(body.app_id)
    if not app or app.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"Application '{body.app_id}' not found."},
        )

    mapping_dal = GroupRoleMappingDAL(db)
    mapping = await mapping_dal.create_mapping(
        org_id=org_id,
        group_id=body.group_id,
        app_id=body.app_id,
        app_role=body.app_role,
    )

    # Immediately grant this role to all current members of the group
    await propagate_new_role_mapping(db, org_id, body.group_id, body.app_id, body.app_role)
    await db.commit()

    return GroupRoleMappingResponse(
        id=str(mapping.id),
        organization_id=str(mapping.organization_id),
        group_id=str(mapping.group_id),
        group_name=group.display_name,
        app_id=str(mapping.app_id),
        app_key=app.app_key,
        app_role=mapping.app_role,
        created_at=mapping.created_at.isoformat(),
    )


@router.get("/organizations/{org_id}/group-role-mappings", response_model=List[GroupRoleMappingResponse])
async def list_group_role_mappings(
    org_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Lists all configured group-to-app-role mappings for the organization."""
    if user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    mapping_dal = GroupRoleMappingDAL(db)
    group_dal = SCIMGroupDAL(db)
    app_dal = AppDAL(db)

    mappings = await mapping_dal.list_for_org(org_id)
    results = []
    for m in mappings:
        grp = await group_dal.get_by_id(m.group_id)
        app = await app_dal.get_by_id(m.app_id)
        results.append(
            GroupRoleMappingResponse(
                id=str(m.id),
                organization_id=str(m.organization_id),
                group_id=str(m.group_id),
                group_name=grp.display_name if grp else "Unknown Group",
                app_id=str(m.app_id),
                app_key=app.app_key if app else "unknown",
                app_role=m.app_role,
                created_at=m.created_at.isoformat(),
            )
        )
    return results


@router.delete("/organizations/{org_id}/group-role-mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_role_mapping(
    org_id: uuid.UUID,
    mapping_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Deletes a group-to-app-role mapping."""
    if user.organization_id != org_id or user.platform_role not in ["owner", "editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization administrators can delete mappings."},
        )

    mapping_dal = GroupRoleMappingDAL(db)
    deleted = await mapping_dal.delete_mapping(mapping_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MAPPING_NOT_FOUND", "message": f"Mapping '{mapping_id}' not found."},
        )
    await db.commit()
