"""
Authentication and current user endpoints.
"""
from fastapi import APIRouter, Depends
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser

router = APIRouter(tags=["Auth"])


@router.get("/auth/me")
@router.get("/auth/status")
async def get_current_user_profile(user: AuthenticatedUser = Depends(get_current_user)):
    """
    Returns the authenticated caller's profile, organization, and platform role.
    """
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.display_name,
        "organization_id": str(user.organization_id),
        "platform_role": user.platform_role,
        "token_type": user.token_type,
    }
