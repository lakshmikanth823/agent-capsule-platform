"""
FastAPI authentication dependencies.
Resolves caller identity from Bearer tokens without trusting client-supplied org or user IDs.
"""
import os
import uuid
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import UserDAL, OrganizationDAL
from .models import AuthenticatedUser
from .provider import AuthenticationError, TokenExpiredError, OIDCProvider
from .mock import MockOIDCProvider
from .google import GoogleOIDCProvider
from .tokens import PublishTokenService

_publish_token_service = PublishTokenService()


def get_oidc_provider() -> OIDCProvider:
    provider_name = os.environ.get("AUTH_PROVIDER", "mock").lower()
    if provider_name == "google":
        return GoogleOIDCProvider()
    return MockOIDCProvider()


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session),
) -> AuthenticatedUser:
    """
    Extracts Bearer token from Authorization header and verifies it.
    Resolves user and organization strictly from the verified token and database state.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Missing or invalid Authorization header."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[len("Bearer ") :].strip()

    # 1. Try Scoped Publish Token first
    try:
        publish_payload = _publish_token_service.verify_publish_token(token)
        user_id = uuid.UUID(publish_payload["sub"])
        org_id = uuid.UUID(publish_payload["org_id"])
        publish_app_id = (
            uuid.UUID(publish_payload["app_id"]) if publish_payload.get("app_id") else None
        )

        user_dal = UserDAL(db)
        user = await user_dal.get_by_id(user_id)
        if not user or user.status != "active":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "USER_INACTIVE", "message": "User account is inactive or not found."},
            )

        # Check org membership
        members = await user_dal.get_org_members(org_id)
        membership = next((m for m in members if m.user_id == user.id), None)
        platform_role = membership.platform_role if membership else "user"

        return AuthenticatedUser(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            organization_id=org_id,
            platform_role=platform_role,
            token_type="publish_token",
            claims=publish_payload,
            publish_app_id=publish_app_id,
        )
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "Publish token has expired."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except AuthenticationError:
        # Not a publish token, try OIDC provider below
        pass

    # 2. Try OIDC Provider
    oidc_provider = get_oidc_provider()
    try:
        claims = await oidc_provider.verify_token(token)
    except TokenExpiredError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": str(e)},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": str(e)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Resolve or Provision User in DB
    email = claims.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CLAIMS", "message": "Token missing email claim."},
        )

    user_dal = UserDAL(db)
    org_dal = OrganizationDAL(db)

    sub = claims.get("sub")
    iss = claims.get("iss", "oidc")

    user = None
    if sub:
        user = await user_dal.get_by_identity(iss, sub)
    if not user:
        user = await user_dal.get_by_email(email)

    # Determine organization
    org_slug = claims.get("org_slug", "acme")
    org = await org_dal.get_by_slug(org_slug)
    if not org:
        org = await org_dal.create(
            slug=org_slug,
            name=claims.get("org_name", org_slug.replace("-", " ").title()),
        )

    platform_role = claims.get("platform_role", "user")

    if not user:
        user = await user_dal.create(
            email=email,
            display_name=claims.get("name", email.split("@")[0]),
            identity_subject=sub,
            identity_issuer=iss,
            status="active",
        )
        await user_dal.add_to_org(org.id, user.id, platform_role=platform_role)
    else:
        # Check if member of org
        members = await user_dal.get_org_members(org.id)
        membership = next((m for m in members if m.user_id == user.id), None)
        if not membership:
            await user_dal.add_to_org(org.id, user.id, platform_role=platform_role)
        else:
            platform_role = membership.platform_role

    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        organization_id=org.id,
        platform_role=platform_role,
        token_type="oidc",
        claims=claims,
    )
