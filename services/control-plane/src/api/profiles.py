"""
Environment Profile Management API (Prompt 17)

Fulfills PRD FR-027, FR-028, FR-032:
- GET /v1/organizations/{org_id}/environment-profile: View active profile & policy ceiling
- PUT /v1/organizations/{org_id}/environment-profile: Update profile, re-evaluate apps, enforce grace period
- POST /v1/organizations/{org_id}/environment-profile/preview-diff: Dry-run diff preview & impact analysis
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import OrganizationDAL, AppDAL, AuditDAL
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from services.policy_engine import (
    DEFAULT_ENVIRONMENT_PROFILE,
    get_effective_profile,
    validate_against_profile,
    compute_profile_diff,
    deep_merge,
)

router = APIRouter(prefix="/organizations", tags=["Environment Profiles"])


class ProfileUpdateRequest(BaseModel):
    profile: Dict[str, Any] = Field(..., description="The complete or partial environment profile specification")


@router.get("/{org_id}/environment-profile")
async def get_environment_profile(
    org_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Retrieve the active Environment Profile and policy ceiling for an organization.
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

    effective = get_effective_profile(org.environment_profile)
    return {
        "organization_id": str(org.id),
        "organization_slug": org.slug,
        "version": effective.get("version", "capsule/v1alpha1"),
        "profile": effective,
        "raw_profile": org.environment_profile or {},
    }


@router.post("/{org_id}/environment-profile/preview-diff")
async def preview_profile_diff(
    org_id: str,
    payload: ProfileUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Dry-run preview: calculates changes between current profile and proposed profile,
    and analyzes impact on all published capsules in the organization.
    """
    if user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization administrators can preview profile changes."},
        )

    org_dal = OrganizationDAL(db)
    app_dal = AppDAL(db)

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

    old_profile = get_effective_profile(org.environment_profile)
    new_profile = get_effective_profile(payload.profile)

    # 1. Compute diff
    diff = compute_profile_diff(old_profile, new_profile)

    # 2. Impact analysis: check all apps in organization
    apps = await app_dal.list_by_org(org.id)
    impacted_apps = []

    for app in apps:
        if app.status == "archived":
            continue
        manifest = app.manifest or {}
        violations = validate_against_profile(manifest, new_profile)
        if violations:
            impacted_apps.append({
                "app_id": str(app.id),
                "app_key": app.app_key,
                "name": app.name,
                "status": app.status,
                "violations": violations,
                "violations_count": len(violations),
            })

    return {
        "organization_id": str(org.id),
        "diff": diff,
        "impacted_apps": impacted_apps,
        "impacted_apps_count": len(impacted_apps),
        "total_apps_evaluated": len(apps),
    }


@router.put("/{org_id}/environment-profile")
async def update_environment_profile(
    org_id: str,
    payload: ProfileUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Update the Environment Profile for an organization.
    Admin-only. Re-evaluates all existing applications and applies grace period.
    """
    if user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization administrators can update environment profiles."},
        )

    org_dal = OrganizationDAL(db)
    app_dal = AppDAL(db)
    audit_dal = AuditDAL(db)

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

    old_profile = get_effective_profile(org.environment_profile)
    # Save the updated profile into DB
    merged_profile = deep_merge(org.environment_profile or {}, payload.profile)
    updated_org = await org_dal.update_environment_profile(org.id, merged_profile)
    new_effective_profile = get_effective_profile(updated_org.environment_profile)

    diff = compute_profile_diff(old_profile, new_effective_profile)

    # Re-evaluate all apps in organization
    apps = await app_dal.list_by_org(org.id)
    grace_hours = new_effective_profile.get("compliance", {}).get("grace_period_hours", 72)
    action = new_effective_profile.get("compliance", {}).get("enforcement_action", "restrict")

    now = datetime.now(timezone.utc)
    grace_expiry = now + timedelta(hours=grace_hours)

    non_compliant_apps = []

    for app in apps:
        if app.status == "archived":
            continue
        manifest = app.manifest or {}
        violations = validate_against_profile(manifest, new_effective_profile)

        if violations:
            compliance_info = {
                "compliance_status": "non_compliant",
                "violations": violations,
                "evaluated_at": now.isoformat(),
                "grace_period_expires_at": grace_expiry.isoformat(),
                "grace_period_hours": grace_hours,
                "action": action,
            }

            # If grace period is 0, enforce immediately
            new_status = None
            suspension_reason = None
            if grace_hours == 0:
                if action == "suspend":
                    new_status = "suspended"
                    suspension_reason = f"Suspended due to non-compliance with updated Environment Profile: {violations[0]['message']}"
                compliance_info["compliance_status"] = "enforced"

            await app_dal.update_compliance_metadata(
                app_id=app.id,
                compliance_info=compliance_info,
                status=new_status,
                suspension_reason=suspension_reason,
            )

            # Record audit event for app compliance warning
            await audit_dal.record_event(
                action="app.compliance_warning" if grace_hours > 0 else "app.compliance_enforced",
                outcome="denied",
                actor_user_id=user.id,
                organization_id=org.id,
                app_id=app.id,
                target_type="app",
                metadata={
                    "app_key": app.app_key,
                    "violations": violations,
                    "grace_period_hours": grace_hours,
                    "grace_period_expires_at": grace_expiry.isoformat(),
                    "enforcement_action": action,
                },
            )

            non_compliant_apps.append({
                "app_id": str(app.id),
                "app_key": app.app_key,
                "violations_count": len(violations),
                "violations": violations,
                "grace_period_expires_at": grace_expiry.isoformat(),
            })
        else:
            # Mark compliant if it was previously flagged
            if manifest.get("_compliance"):
                compliance_info = {
                    "compliance_status": "compliant",
                    "violations": [],
                    "evaluated_at": now.isoformat(),
                }
                await app_dal.update_compliance_metadata(app.id, compliance_info)

    # Record overall audit event
    await audit_dal.record_event(
        action="organization.environment_profile_updated",
        outcome="success",
        actor_user_id=user.id,
        organization_id=org.id,
        target_type="organization",
        metadata={
            "diff": diff,
            "impacted_apps_count": len(non_compliant_apps),
            "total_apps": len(apps),
            "grace_period_hours": grace_hours,
        },
    )

    await db.commit()

    return {
        "organization_id": str(org.id),
        "status": "updated",
        "profile": new_effective_profile,
        "diff": diff,
        "re_evaluation": {
            "total_apps_evaluated": len(apps),
            "non_compliant_apps_count": len(non_compliant_apps),
            "non_compliant_apps": non_compliant_apps,
            "grace_period_hours": grace_hours,
            "grace_period_expires_at": grace_expiry.isoformat(),
        },
        "message": f"Environment profile updated. {len(non_compliant_apps)} non-compliant apps flagged with {grace_hours}h grace period.",
    }
