"""
Audit API Endpoints
Provides filtered viewing, pagination, detail inspection, streaming export (CSV/JSON),
cryptographic hash chain verification, retention enforcement, and webhook destinations.
"""
import csv
import io
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.models import App, Organization, OrganizationAuditWebhook
from db.dal import AuditDAL, AuditWebhookDAL
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from services.audit_retention import AuditRetentionService
from services.audit_webhook import dispatch_audit_webhook
from crypto import decrypt_secret

router = APIRouter(tags=["Audit"])


class WebhookConfigPayload(BaseModel):
    url: str
    secret_token: Optional[str] = None
    is_active: bool = True


async def _resolve_access_scope(
    user: AuthenticatedUser,
    org_id: uuid.UUID,
    requested_app_id: Optional[uuid.UUID],
    db: AsyncSession,
) -> Optional[List[uuid.UUID]]:
    """
    Validates permissions. Org admins see all events.
    App owners only see events for apps they own.
    Returns:
      - None if user is org admin (no app restriction)
      - List[uuid.UUID] of owned app IDs if user is an app owner
      - Raises 403 Forbidden otherwise
    """
    if user.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: cannot access audit logs of another organization",
        )

    if user.platform_role in ("owner", "editor"):
        return None

    # Normal user: verify if they own any apps
    res = await db.execute(
        select(App.id).where(
            App.organization_id == org_id,
            App.owner_user_id == user.id,
        )
    )
    owned_ids = [row[0] for row in res.all()]

    if not owned_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: only organization admins and app owners can view audit logs",
        )

    if requested_app_id is not None:
        if requested_app_id not in owned_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: you do not own the requested app",
            )
        return [requested_app_id]

    return owned_ids


def _serialize_audit_event(e: Any) -> Dict[str, Any]:
    return {
        "id": str(e.id),
        "sequence_number": getattr(e, "sequence_number", None),
        "prev_hash": getattr(e, "prev_hash", None),
        "event_hash": getattr(e, "event_hash", None),
        "action": e.action,
        "outcome": e.outcome,
        "organization_id": str(e.organization_id) if e.organization_id else None,
        "app_id": str(e.app_id) if e.app_id else None,
        "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
        "actor_agent": getattr(e, "actor_agent", None),
        "actor_tool": getattr(e, "actor_tool", None),
        "target_type": e.target_type,
        "target_id": str(e.target_id) if e.target_id else None,
        "ip_address": str(e.ip_address) if e.ip_address else None,
        "user_agent": e.user_agent,
        "metadata": e.metadata_,
        "occurred_at": e.occurred_at.isoformat(),
    }


# Backwards-compatible /audit/events endpoint
@router.get("/audit/events")
async def list_audit_events_legacy(
    app_id: Optional[uuid.UUID] = Query(None),
    actor_user_id: Optional[uuid.UUID] = Query(None),
    agent_or_tool: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    res = await list_org_audit_events(
        org_id=user.organization_id,
        app_id=app_id,
        actor_user_id=actor_user_id,
        agent_or_tool=agent_or_tool,
        action=action,
        outcome=outcome,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
        user=user,
        db=db,
    )
    return res["items"]


@router.get("/organizations/{org_id}/audit/events")
async def list_org_audit_events(
    org_id: uuid.UUID,
    app_id: Optional[uuid.UUID] = Query(None),
    actor_user_id: Optional[uuid.UUID] = Query(None),
    agent_or_tool: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    List audit events with rich filtering, pagination, and role-based scoping.
    """
    app_scope = await _resolve_access_scope(user, org_id, app_id, db)
    audit_dal = AuditDAL(db)

    events, total = await audit_dal.list_events_filtered(
        organization_id=org_id,
        app_id=app_id if app_scope is None else None,
        app_ids_scope=app_scope,
        actor_user_id=actor_user_id,
        agent_or_tool=agent_or_tool,
        action=action,
        outcome=outcome,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )

    return {
        "items": [_serialize_audit_event(e) for e in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/organizations/{org_id}/audit/events/{event_id}")
async def get_audit_event_detail(
    org_id: uuid.UUID,
    event_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Retrieve full details for a single audit event.
    """
    app_scope = await _resolve_access_scope(user, org_id, None, db)
    audit_dal = AuditDAL(db)
    event = await audit_dal.get_by_id(event_id)

    if not event or event.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit event not found",
        )

    if app_scope is not None and event.app_id not in app_scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: you do not own the app associated with this audit event",
        )

    return _serialize_audit_event(event)


@router.get("/organizations/{org_id}/audit/export")
async def export_audit_events(
    org_id: uuid.UUID,
    format: str = Query("json", pattern="^(json|csv)$"),
    app_id: Optional[uuid.UUID] = Query(None),
    actor_user_id: Optional[uuid.UUID] = Query(None),
    agent_or_tool: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Export audit events in CSV or JSON format with stream response.
    """
    app_scope = await _resolve_access_scope(user, org_id, app_id, db)
    audit_dal = AuditDAL(db)

    # Fetch all matching events up to 10,000 for export
    events, _ = await audit_dal.list_events_filtered(
        organization_id=org_id,
        app_id=app_id if app_scope is None else None,
        app_ids_scope=app_scope,
        actor_user_id=actor_user_id,
        agent_or_tool=agent_or_tool,
        action=action,
        outcome=outcome,
        start_time=start_time,
        end_time=end_time,
        limit=10000,
        offset=0,
    )

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id",
            "occurred_at",
            "sequence_number",
            "action",
            "outcome",
            "actor_user_id",
            "actor_agent",
            "actor_tool",
            "app_id",
            "target_type",
            "target_id",
            "ip_address",
            "prev_hash",
            "event_hash",
        ])
        for e in events:
            writer.writerow([
                str(e.id),
                e.occurred_at.isoformat(),
                e.sequence_number,
                e.action,
                e.outcome,
                str(e.actor_user_id) if e.actor_user_id else "",
                e.actor_agent or "",
                e.actor_tool or "",
                str(e.app_id) if e.app_id else "",
                e.target_type or "",
                str(e.target_id) if e.target_id else "",
                str(e.ip_address) if e.ip_address else "",
                e.prev_hash,
                e.event_hash,
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="audit_export_{org_id}.csv"'
            },
        )
    else:
        # JSON streaming lines
        serialized = [_serialize_audit_event(e) for e in events]
        json_content = json.dumps(serialized, indent=2)
        return StreamingResponse(
            iter([json_content]),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="audit_export_{org_id}.json"'
            },
        )


@router.post("/organizations/{org_id}/audit/verify")
async def verify_audit_hash_chain(
    org_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Verifies cryptographic hash chain integrity for the organization.
    Detects any sequence gaps, modified event content, or broken links.
    Only available to organization admins.
    """
    if user.organization_id != org_id or user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: only organization admins can verify the audit hash chain",
        )

    audit_dal = AuditDAL(db)
    report = await audit_dal.verify_chain(org_id)
    return report


@router.post("/organizations/{org_id}/audit/retention/enforce")
async def enforce_audit_retention(
    org_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Enforces the organization's retention policy. Older records are purged
    and a cryptographic checkpoint is recorded to preserve chain continuity.
    Only available to organization admins.
    """
    if user.organization_id != org_id or user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: only organization admins can enforce audit retention",
        )

    retention_svc = AuditRetentionService(db)
    result = await retention_svc.enforce_organization_retention(org_id)
    return result


@router.get("/organizations/{org_id}/audit/webhook")
async def get_audit_webhook(
    org_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Retrieve external streaming webhook destination for audit logs.
    Only available to organization admins.
    """
    if user.organization_id != org_id or user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: only organization admins can manage audit webhooks",
        )

    webhook_dal = AuditWebhookDAL(db)
    webhook = await webhook_dal.get_by_org(org_id)
    if not webhook:
        return {"configured": False, "webhook": None}

    return {
        "configured": True,
        "webhook": {
            "id": str(webhook.id),
            "url": webhook.url,
            "has_secret": webhook.secret_token_encrypted is not None,
            "is_active": webhook.is_active,
            "created_at": webhook.created_at.isoformat(),
            "updated_at": webhook.updated_at.isoformat(),
        },
    }


@router.put("/organizations/{org_id}/audit/webhook")
async def update_audit_webhook(
    org_id: uuid.UUID,
    payload: WebhookConfigPayload,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Configure or update streaming webhook destination for audit logs.
    Only available to organization admins.
    """
    if user.organization_id != org_id or user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: only organization admins can manage audit webhooks",
        )

    webhook_dal = AuditWebhookDAL(db)
    webhook = await webhook_dal.upsert_webhook(
        organization_id=org_id,
        url=str(payload.url),
        secret_token=payload.secret_token,
        is_active=payload.is_active,
    )

    return {
        "id": str(webhook.id),
        "url": webhook.url,
        "has_secret": webhook.secret_token_encrypted is not None,
        "is_active": webhook.is_active,
        "updated_at": webhook.updated_at.isoformat(),
    }


@router.delete("/organizations/{org_id}/audit/webhook")
async def delete_audit_webhook(
    org_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Delete streaming webhook configuration.
    """
    if user.organization_id != org_id or user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: only organization admins can manage audit webhooks",
        )

    webhook_dal = AuditWebhookDAL(db)
    deleted = await webhook_dal.delete_webhook(org_id)
    return {"deleted": deleted}


@router.post("/organizations/{org_id}/audit/webhook/test")
async def test_audit_webhook(
    org_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Send a test audit event payload to the configured webhook.
    """
    if user.organization_id != org_id or user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: only organization admins can test audit webhooks",
        )

    webhook_dal = AuditWebhookDAL(db)
    webhook = await webhook_dal.get_by_org(org_id)
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No audit webhook configured for this organization",
        )

    secret = (
        decrypt_secret(webhook.secret_token_encrypted)
        if webhook.secret_token_encrypted
        else None
    )
    test_event = {
        "id": str(uuid.uuid4()),
        "organization_id": str(org_id),
        "action": "audit.webhook.test",
        "outcome": "success",
        "actor_user_id": str(user.id),
        "actor_agent": "system",
        "actor_tool": "test_runner",
        "metadata": {"test": True, "initiated_by": user.email},
        "occurred_at": datetime.now().isoformat(),
    }
    delivered = await dispatch_audit_webhook(webhook.url, secret, test_event)
    return {
        "delivered": delivered,
        "url": webhook.url,
        "event": test_event,
    }
