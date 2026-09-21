"""
Token management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import AppDAL, AuditDAL
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from auth.tokens import PublishTokenService
from .schemas import CreatePublishTokenRequest, PublishTokenResponse

router = APIRouter(tags=["Tokens"])
_publish_service = PublishTokenService()


@router.post("/tokens/publish", response_model=PublishTokenResponse)
async def create_publish_token(
    request: CreatePublishTokenRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Issue a short-lived scoped publish token.
    Token can be scoped to a specific app or across all apps in the user's organization.
    """
    app_dal = AppDAL(db)
    audit_dal = AuditDAL(db)

    if request.app_id:
        app = await app_dal.get_by_id(request.app_id)
        if not app or app.organization_id != user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "APP_NOT_FOUND", "message": f"App '{request.app_id}' not found."},
            )

    token_data = _publish_service.create_publish_token(
        user_id=user.id,
        organization_id=user.organization_id,
        app_id=request.app_id,
        expires_in_seconds=request.expires_in_seconds,
    )

    # Record audit event
    await audit_dal.record_event(
        action="token.create",
        outcome="success",
        organization_id=user.organization_id,
        app_id=request.app_id,
        actor_user_id=user.id,
        target_type="publish_token",
        metadata={
            "scope": token_data["scope"],
            "expires_in": token_data["expires_in"],
            "jti": token_data["jti"],
        },
    )
    await db.commit()

    return PublishTokenResponse(**token_data)
