"""
Audit inspection endpoints.
"""
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import AuditDAL
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser

router = APIRouter(tags=["Audit"])


@router.get("/audit/events")
async def list_audit_events(
    app_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """
    Retrieve audit events for the caller's organization.
    """
    audit_dal = AuditDAL(db)
    events = await audit_dal.list_events(
        organization_id=user.organization_id,
        app_id=app_id,
        limit=limit,
    )
    return [
        {
            "id": str(e.id),
            "action": e.action,
            "outcome": e.outcome,
            "organization_id": str(e.organization_id) if e.organization_id else None,
            "app_id": str(e.app_id) if e.app_id else None,
            "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
            "target_type": e.target_type,
            "target_id": str(e.target_id) if e.target_id else None,
            "metadata": e.metadata_,
            "occurred_at": e.occurred_at.isoformat(),
        }
        for e in events
    ]
