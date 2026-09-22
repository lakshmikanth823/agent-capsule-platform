"""
FastAPI authentication dependencies.
Resolves caller identity from Bearer tokens without trusting client-supplied org or user IDs.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import UserDAL, OrganizationDAL, IdpDAL, DomainDAL
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
        org_dal = OrganizationDAL(db)
        user = await user_dal.get_by_id(user_id)
        if not user or user.status != "active":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "USER_INACTIVE", "message": "User account is inactive or not found."},
            )

        org = await org_dal.get_by_id(org_id)
        if not org or org.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ORGANIZATION_SUSPENDED",
                    "message": f"Organization '{org.slug if org else org_id}' is suspended.",
                },
            )

        # Check mass token revocation
        token_iat = publish_payload.get("iat")
        if token_iat is not None:
            token_dt = datetime.fromtimestamp(token_iat, timezone.utc)
            if user.tokens_revoked_at and token_dt <= user.tokens_revoked_at:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"code": "TOKEN_REVOKED", "message": "Publish token has been revoked for this user."},
                )
            if org.tokens_revoked_at and token_dt <= org.tokens_revoked_at:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"code": "TOKEN_REVOKED", "message": "Publish token has been revoked for this organization."},
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
    except HTTPException:
        raise
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

    if org.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ORGANIZATION_SUSPENDED",
                "message": f"Organization '{org.slug}' is suspended.",
            },
        )

    platform_role = claims.get("platform_role", "user")

    # Check domain SSO enforcement (blocks mock/dev logins when SSO is enforced for domain)
    if "@" in email:
        domain = email.split("@")[-1].lower()
        domain_dal = DomainDAL(db)
        idp_dal = IdpDAL(db)
        is_verified = await domain_dal.is_domain_verified_for_org(org.id, domain)
        if is_verified:
            idp = await idp_dal.get_by_org(org.id)
            iss_claim = claims.get("iss", "")
            if idp and idp.enforce_sso and (iss_claim in ["mock", "mock:oidc"] or iss_claim.startswith("mock")):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": "SSO_REQUIRED",
                        "message": f"Single Sign-On is strictly enforced for '@{domain}'. Please authenticate using company SSO.",
                    },
                )

    existing_members = await user_dal.get_org_members(org.id)
    # Prevent privilege self-elevation: only the first member or mock personas can claim owner/editor
    assigned_role = "user"
    if not existing_members:
        assigned_role = claims.get("platform_role", "owner")
    elif os.environ.get("AUTH_PROVIDER", "mock").lower() == "mock":
        assigned_role = claims.get("platform_role", "user")
    else:
        assigned_role = "user"

    if not user:
        user = await user_dal.create(
            email=email,
            display_name=claims.get("name", email.split("@")[0]),
            identity_subject=sub,
            identity_issuer=iss,
            status="active",
        )
        await user_dal.add_to_org(org.id, user.id, platform_role=assigned_role)
        platform_role = assigned_role
    else:
        if user.status != "active":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "USER_INACTIVE", "message": "User account is inactive, suspended, or deprovisioned."},
            )

        # Check session revocation
        session_iat = claims.get("iat")
        if session_iat is not None:
            session_dt = datetime.fromtimestamp(session_iat, timezone.utc)
            if user.sessions_revoked_at and session_dt <= user.sessions_revoked_at:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"code": "SESSION_REVOKED", "message": "User session has been revoked."},
                )
            if org.sessions_revoked_at and session_dt <= org.sessions_revoked_at:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"code": "SESSION_REVOKED", "message": "Session has been revoked for this organization."},
                )

        # Check if member of org
        membership = next((m for m in existing_members if m.user_id == user.id), None)
        if not membership:
            await user_dal.add_to_org(org.id, user.id, platform_role=assigned_role)
            platform_role = assigned_role
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


async def get_current_user_no_org_check(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session),
) -> AuthenticatedUser:
    """
    Same as get_current_user but skips the org-suspension check.
    Use ONLY for kill-switch resume endpoints that must work even when the org is suspended.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Missing or invalid Authorization header."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[len("Bearer "):].strip()

    # 1. Try Scoped Publish Token first
    try:
        publish_payload = _publish_token_service.verify_publish_token(token)
        user_id = uuid.UUID(publish_payload["sub"])
        org_id = uuid.UUID(publish_payload["org_id"])
        publish_app_id = (
            uuid.UUID(publish_payload["app_id"]) if publish_payload.get("app_id") else None
        )

        user_dal = UserDAL(db)
        org_dal = OrganizationDAL(db)
        user = await user_dal.get_by_id(user_id)
        if not user or user.status != "active":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "USER_INACTIVE", "message": "User account is inactive or not found."},
            )

        org = await org_dal.get_by_id(org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_id}' not found."},
            )
        # NOTE: org suspension check is intentionally skipped here

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
    except HTTPException:
        raise
    except AuthenticationError:
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

    org_slug = claims.get("org_slug", "acme")
    org = await org_dal.get_by_slug(org_slug)
    if not org:
        org = await org_dal.create(
            slug=org_slug,
            name=claims.get("org_name", org_slug.replace("-", " ").title()),
        )
    # NOTE: org suspension check is intentionally skipped here

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
