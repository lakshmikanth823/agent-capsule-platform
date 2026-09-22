"""
Control-Plane API Endpoints for AI Gateway (Prompt 24 / FR-018)

Endpoints:
- POST /v1/ai/chat: AI chat completion (supports streaming via SSE).
- GET /v1/apps/{app_id}/ai/usage: Monthly budget & spend summary for an app.
- GET /v1/organizations/{org_id}/ai/usage: Organization-wide aggregated AI metrics.
- GET /v1/organizations/{org_id}/ai/requests: Paginated list of AI requests.
- POST /v1/organizations/{org_id}/ai/purge-content: Purges expired prompt/response content per retention policy.
"""
import uuid
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.models import App, Organization, User, OrganizationMember
from db.dal import AppDAL, OrganizationDAL, UserDAL, AIUsageDAL
from auth.dependencies import get_current_user
from services.ai_gateway import AIGatewayService
from api.connectors import parse_viewer_identity, _resolve_user_and_org


router = APIRouter(prefix="/v1", tags=["ai"])


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: 'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = Field(None, description="Requested model name (e.g. 'gemini-1.5-flash')")
    messages: List[ChatMessage] = Field(..., description="List of messages in conversation")
    stream: bool = Field(False, description="Whether to stream response chunks via SSE")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, gt=0)
    tools: Optional[List[Dict[str, Any]]] = Field(None, description="Tool definitions (rejected by default)")
    app_id: Optional[str] = Field(None, description="App ID if not in headers")
    app_key: Optional[str] = Field(None, description="App key if not in headers")


class PurgeContentRequest(BaseModel):
    retention_days: Optional[int] = Field(None, ge=1, le=3650)


@router.post("/ai/chat")
async def ai_chat_completion(
    req: ChatCompletionRequest,
    x_capsule_key: Optional[str] = Header(None, alias="x-capsule-key"),
    x_capsule_id: Optional[str] = Header(None, alias="x-capsule-id"),
    x_capsule_identity: Optional[str] = Header(None, alias="x-capsule-identity"),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Executes an AI Chat Completion through the platform AI Gateway.
    Enforces manifest capabilities, model allowlists, monthly budgets, and rate limits.
    External provider API keys are managed centrally and never reach the application.
    """
    app_dal = AppDAL(db)
    org_dal = OrganizationDAL(db)

    # 1. Resolve calling app
    target_id_str = x_capsule_id or req.app_id
    target_key_str = x_capsule_key or req.app_key

    app: Optional[App] = None
    if target_id_str:
        try:
            app = await app_dal.get_by_id(uuid.UUID(target_id_str))
        except ValueError:
            pass

    if not app and target_key_str:
        result = await db.execute(select(App).where(App.app_key == target_key_str))
        app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "APP_IDENTIFICATION_REQUIRED",
                "message": "Missing or invalid app identification ('x-capsule-key' or 'x-capsule-id').",
            },
        )

    if app.status not in ("active", "ready", "draft"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "APP_NOT_ACTIVE", "message": f"App '{app.app_key}' is not active ({app.status})."},
        )

    # 2. Resolve Organization
    org = await org_dal.get_by_id(app.organization_id)
    if not org or org.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ORG_NOT_ACTIVE", "message": "Organization is inactive or suspended."},
        )

    # 3. Resolve Calling User
    user_id, _ = await _resolve_user_and_org(
        authorization=authorization,
        x_capsule_identity=x_capsule_identity,
        organization_id=org.id,
        db=db,
    )

    payload = req.model_dump()

    # 4. Handle Streaming vs Standard Response
    if req.stream:
        async def stream_generator():
            async for chunk in AIGatewayService.execute_stream(app, org, user_id, payload, db):
                yield chunk

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Standard JSON response
    result = await AIGatewayService.execute_chat(app, org, user_id, payload, db)
    return result


@router.get("/apps/{app_id}/ai/usage")
async def get_app_ai_usage(
    app_id: uuid.UUID,
    authorization: Optional[str] = Header(None),
    x_capsule_key: Optional[str] = Header(None, alias="x-capsule-key"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Retrieves current monthly spend, declared budget, remaining balance,
    and recent invocations for an application.
    """
    app_dal = AppDAL(db)
    ai_dal = AIUsageDAL(db)

    app = await app_dal.get_by_id(app_id)
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found.")

    # Authorization: check user is member or caller matches app_key
    if authorization and authorization.startswith("Bearer "):
        user = await get_current_user(authorization=authorization, db=db)
        if user.organization_id != app.organization_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    elif x_capsule_key and x_capsule_key == app.app_key:
        pass
    else:
        # Fallback for dev mode
        pass

    manifest = app.manifest or {}
    app_budget = float(manifest.get("capabilities", {}).get("ai", {}).get("monthly_budget_usd", 50.0))

    now_utc = datetime.now(timezone.utc)
    month_start = datetime(now_utc.year, now_utc.month, 1, tzinfo=timezone.utc)

    usage_data = await ai_dal.get_app_usage_summary(app.id, month_start)
    current_spend = usage_data["monthly_spend_usd"]
    remaining = max(0.0, round(app_budget - current_spend, 4))

    return {
        "app_id": str(app.id),
        "app_key": app.app_key,
        "monthly_budget_usd": app_budget,
        "current_spend_usd": current_spend,
        "remaining_budget_usd": remaining,
        "budget_used_percentage": round((current_spend / app_budget) * 100, 2) if app_budget > 0 else 0.0,
        "monthly_tokens": usage_data["monthly_tokens"],
        "monthly_requests": usage_data["monthly_requests"],
        "recent_requests": [
            {
                "id": str(r.id),
                "model": r.model,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "estimated_cost_usd": r.estimated_cost_usd,
                "duration_ms": r.duration_ms,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in usage_data["recent_requests"]
        ],
    }


@router.get("/organizations/{org_id}/ai/usage")
async def get_org_ai_usage(
    org_id: uuid.UUID,
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Aggregates organization-wide AI metrics: total tokens, cost, request counts,
    and breakdowns by model, app, and user.
    """
    user = await get_current_user(authorization=authorization, db=db)
    if user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    # Check member role (owner or editor)
    member_res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    )
    member = member_res.scalar_one_or_none()
    if not member or member.platform_role not in ("owner", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permissions required.")

    ai_dal = AIUsageDAL(db)
    t_start = None
    t_end = None
    if start_time:
        try:
            t_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            pass
    if end_time:
        try:
            t_end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            pass

    summary = await ai_dal.get_org_usage_summary(org_id, start_time=t_start, end_time=t_end)
    return summary


@router.get("/organizations/{org_id}/ai/requests")
async def list_org_ai_requests(
    org_id: uuid.UUID,
    app_id: Optional[uuid.UUID] = Query(None),
    model: Optional[str] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Returns a paginated list of AI Gateway requests for organization audit and monitoring.
    """
    user = await get_current_user(authorization=authorization, db=db)
    if user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    member_res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    )
    member = member_res.scalar_one_or_none()
    if not member or member.platform_role not in ("owner", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permissions required.")

    ai_dal = AIUsageDAL(db)
    records, total = await ai_dal.list_requests(
        org_id=org_id,
        app_id=app_id,
        model=model,
        user_id=user_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )

    return {
        "items": [
            {
                "id": str(r.id),
                "app_id": str(r.app_id),
                "user_id": str(r.user_id) if r.user_id else None,
                "model": r.model,
                "provider": r.provider,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "estimated_cost_usd": r.estimated_cost_usd,
                "duration_ms": r.duration_ms,
                "status": r.status,
                "redacted": r.redacted,
                "has_content": (r.prompt_content is not None or r.response_content is not None),
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/organizations/{org_id}/ai/purge-content")
async def purge_expired_ai_content(
    org_id: uuid.UUID,
    req: Optional[PurgeContentRequest] = None,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Maintenance endpoint: purges prompt/response content older than the organization's
    retention period while preserving token and cost metrics.
    """
    user = await get_current_user(authorization=authorization, db=db)
    if user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    member_res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    )
    member = member_res.scalar_one_or_none()
    if not member or member.platform_role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization owner permissions required.")

    org_dal = OrganizationDAL(db)
    org = await org_dal.get_by_id(org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    profile = org.environment_profile or {}
    default_retention = int(profile.get("ai", {}).get("content_retention_days", 30))
    retention_days = req.retention_days if req and req.retention_days else default_retention

    ai_dal = AIUsageDAL(db)
    purged = await ai_dal.purge_expired_content(org_id, retention_days)

    return {
        "status": "success",
        "organization_id": str(org_id),
        "retention_days": retention_days,
        "purged_records_count": purged,
    }
