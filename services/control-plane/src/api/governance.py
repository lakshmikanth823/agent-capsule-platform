"""
Governance & Application Inventory API Endpoints (Prompt 20 / FR-033 to FR-036).
Supports:
- POST /v1/apps/{app_id}/transfer-ownership
- PATCH /v1/apps/{app_id}/governance
- POST /v1/apps/{app_id}/activity
- GET /v1/organizations/{org_id}/inventory
- GET /v1/organizations/{org_id}/inventory/export
- POST /v1/organizations/{org_id}/governance/run-cycle
- GET /v1/apps/{app_id}/export-data
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import AppDAL, OrganizationDAL, UserDAL
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from services.governance import GovernanceService

router = APIRouter(tags=["Governance"])


class TransferOwnershipRequest(BaseModel):
    new_owner_user_id: uuid.UUID = Field(..., description="UUID of the new app owner")
    reason: Optional[str] = Field("Manual ownership transfer", description="Transfer reason for audit log")


class GovernanceSettingsRequest(BaseModel):
    nominated_owner_user_id: Optional[uuid.UUID] = Field(None, description="Nominated backup owner")
    expires_at: Optional[datetime] = Field(None, description="Explicit expiration timestamp")
    inactivity_days_limit: Optional[int] = Field(None, description="Inactivity limit in days before warning/archival")
    purge_after_days: Optional[int] = Field(30, description="Grace period in days between archival and permanent purge")


class ActivityRecordRequest(BaseModel):
    timestamp: Optional[datetime] = Field(None, description="Activity timestamp (defaults to now)")


class RunCycleRequest(BaseModel):
    current_time: Optional[datetime] = Field(None, description="Simulated current time for lifecycle evaluation")


@router.post("/apps/{app_id}/transfer-ownership")
async def transfer_ownership(
    app_id: str,
    payload: TransferOwnershipRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Transfer ownership of an application (FR-033 / Prompt 20).
    Authorized for current App Owner or Organization Admin.
    """
    app_dal = AppDAL(db)
    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    gov_service = GovernanceService(db)
    try:
        updated_app = await gov_service.transfer_ownership(
            app_id=app.id,
            new_owner_user_id=payload.new_owner_user_id,
            actor_user=user,
            reason=payload.reason or "Manual ownership transfer",
        )
        return {
            "id": str(updated_app.id),
            "app_key": updated_app.app_key,
            "name": updated_app.name,
            "owner_user_id": str(updated_app.owner_user_id),
            "status": updated_app.status,
            "governance_state": updated_app.governance_state,
            "message": "Ownership transferred successfully.",
        }
    except PermissionError as pe:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": str(pe)},
        )
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_ARGUMENT", "message": str(ve)},
        )


@router.patch("/apps/{app_id}/governance")
async def update_governance_settings(
    app_id: str,
    payload: GovernanceSettingsRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Update per-application governance settings: nominee, expiry, inactivity limit, and retention window.
    """
    app_dal = AppDAL(db)
    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    gov_service = GovernanceService(db)
    try:
        updated_app = await gov_service.update_governance_settings(
            app_id=app.id,
            actor_user=user,
            nominated_owner_user_id=payload.nominated_owner_user_id,
            expires_at=payload.expires_at,
            inactivity_days_limit=payload.inactivity_days_limit,
            purge_after_days=payload.purge_after_days,
        )
        return {
            "id": str(updated_app.id),
            "app_key": updated_app.app_key,
            "nominated_owner_user_id": str(updated_app.nominated_owner_user_id) if updated_app.nominated_owner_user_id else None,
            "expires_at": updated_app.expires_at.isoformat() if updated_app.expires_at else None,
            "inactivity_days_limit": updated_app.inactivity_days_limit,
            "purge_after_days": updated_app.purge_after_days,
            "governance_state": updated_app.governance_state,
        }
    except PermissionError as pe:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": str(pe)},
        )
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_ARGUMENT", "message": str(ve)},
        )


@router.post("/apps/{app_id}/activity")
async def record_activity(
    app_id: str,
    payload: Optional[ActivityRecordRequest] = None,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Record last activity timestamp for an application to track inactivity-based expiry.
    """
    app_dal = AppDAL(db)
    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    activity_time = payload.timestamp if payload and payload.timestamp else datetime.now(timezone.utc)
    gov_service = GovernanceService(db)
    await gov_service.record_activity(app.id, activity_time)
    return {"status": "ok", "app_id": str(app.id), "last_activity_at": activity_time.isoformat()}


@router.get("/organizations/{org_id}/inventory")
async def get_inventory(
    org_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    FR-036 Application Inventory endpoint.
    Lists every app with owner, status, user count, capabilities, last activity, version, and expiry status.
    """
    org_dal = OrganizationDAL(db)
    try:
        val_uuid = uuid.UUID(org_id)
        org = await org_dal.get_by_id(val_uuid)
    except ValueError:
        org = await org_dal.get_by_slug(org_id)

    if not org or org.id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_id}' not found."},
        )

    gov_service = GovernanceService(db)
    items = await gov_service.get_inventory(org.id)
    return {"organization_id": str(org.id), "items": items, "total": len(items)}


@router.get("/organizations/{org_id}/inventory/export")
async def export_inventory(
    org_id: str,
    format: str = Query("json", pattern="^(json|csv)$"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Export application inventory to CSV or JSON format.
    """
    org_dal = OrganizationDAL(db)
    try:
        val_uuid = uuid.UUID(org_id)
        org = await org_dal.get_by_id(val_uuid)
    except ValueError:
        org = await org_dal.get_by_slug(org_id)

    if not org or org.id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_id}' not found."},
        )

    gov_service = GovernanceService(db)
    items = await gov_service.get_inventory(org.id)

    if format == "csv":
        csv_data = gov_service.export_inventory_csv(items)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="inventory-{org.slug}-{datetime.now(timezone.utc).strftime("%Y%m%d")}.csv"'
            },
        )

    return {"organization_id": str(org.id), "items": items, "total": len(items)}


@router.post("/organizations/{org_id}/governance/run-cycle")
async def run_governance_cycle(
    org_id: str,
    payload: Optional[RunCycleRequest] = None,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Execute background governance lifecycle evaluation cycle.
    Detects unowned apps past grace period, sends expiry warnings, archives expired apps, and purges past retention.
    """
    org_dal = OrganizationDAL(db)
    try:
        val_uuid = uuid.UUID(org_id)
        org = await org_dal.get_by_id(val_uuid)
    except ValueError:
        org = await org_dal.get_by_slug(org_id)

    if not org or org.id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_id}' not found."},
        )

    if user.platform_role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization administrators may run governance cycles."},
        )

    current_time = payload.current_time if payload and payload.current_time else datetime.now(timezone.utc)
    gov_service = GovernanceService(db)
    stats = await gov_service.run_governance_cycle(org_id=org.id, current_time=current_time)

    return {
        "organization_id": str(org.id),
        "evaluated_at": current_time.isoformat(),
        "stats": stats,
    }


@router.get("/apps/{app_id}/export-data")
async def export_app_data(
    app_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Generate and download capsule data export snapshot before or during archival.
    """
    app_dal = AppDAL(db)
    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    is_org_admin = (
        user.platform_role == "owner"
        and app.organization_id == user.organization_id
    )
    is_owner = app.owner_user_id == user.id
    if not (is_org_admin or is_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only app owners or org admins can export app data."},
        )

    export_snapshot = {
        "export_metadata": {
            "app_id": str(app.id),
            "app_key": app.app_key,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exported_by": user.email,
        },
        "app": {
            "name": app.name,
            "description": app.description,
            "shape": app.shape,
            "runtime": app.runtime,
            "status": app.status,
            "governance_state": app.governance_state,
            "manifest": app.manifest,
            "created_at": app.created_at.isoformat() if app.created_at else None,
            "last_activity_at": app.last_activity_at.isoformat() if app.last_activity_at else None,
        },
    }

    content_bytes = json.dumps(export_snapshot, indent=2).encode("utf-8")
    return Response(
        content=content_bytes,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="capsule-export-{app.app_key}-{datetime.now(timezone.utc).strftime("%Y%m%d")}.json"'
        },
    )
