"""
Single Sign-On (SSO) API: OIDC & SAML 2.0 configuration, SP metadata,
authorization dispatch, and callback handling with JIT provisioning.
"""
import os
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import jwt
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import IdpDAL, DomainDAL, UserDAL, OrganizationDAL, ReplayDAL
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from auth.sso.oidc import OIDCService, OIDCError
from auth.sso.saml import SAMLService, SAMLError

router = APIRouter(tags=["SSO"])

DEFAULT_SECRET = "control-plane-dev-jwt-secret-do-not-use-in-prod"
_oidc_service = OIDCService()
_saml_service = SAMLService()


class IdpConfigRequest(BaseModel):
    provider_type: str = Field(..., description="'oidc' or 'saml'")
    is_active: bool = True
    enforce_sso: bool = False
    session_lifetime_seconds: int = Field(28800, ge=300, le=604800)
    # OIDC fields
    oidc_issuer_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_discovery_url: Optional[str] = None
    oidc_scopes: Optional[List[str]] = None
    # SAML fields
    saml_entity_id: Optional[str] = None
    saml_sso_url: Optional[str] = None
    saml_slo_url: Optional[str] = None
    saml_x509_cert: Optional[str] = None
    saml_sp_entity_id: Optional[str] = "urn:capsule:sp"
    saml_acs_url: Optional[str] = None


class IdpConfigResponse(BaseModel):
    id: str
    organization_id: str
    provider_type: str
    is_active: bool
    enforce_sso: bool
    session_lifetime_seconds: int
    oidc_issuer_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_discovery_url: Optional[str] = None
    oidc_scopes: Optional[List[str]] = None
    saml_entity_id: Optional[str] = None
    saml_sso_url: Optional[str] = None
    saml_slo_url: Optional[str] = None
    saml_sp_entity_id: Optional[str] = None
    saml_acs_url: Optional[str] = None
    created_at: str
    updated_at: str


def _generate_app_ticket(
    user_id: uuid.UUID,
    email: str,
    org_id: uuid.UUID,
    platform_role: str,
    target_app: str,
    session_lifetime_seconds: int = 28800,
) -> str:
    secret = os.environ.get("SESSION_SECRET", os.environ.get("JWT_SECRET", DEFAULT_SECRET))
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "sub": str(user_id),
        "email": email,
        "org_id": str(org_id),
        "platform_role": platform_role,
        "target_app": target_app,
        "iat": now,
        "exp": now + session_lifetime_seconds,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ==========================================
# IdP Management Endpoints
# ==========================================

@router.put("/organizations/{org_id}/sso/idp", response_model=IdpConfigResponse)
async def configure_idp(
    org_id: uuid.UUID,
    body: IdpConfigRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Configures or updates generic OIDC or SAML 2.0 Identity Provider for an organization."""
    if user.organization_id != org_id or user.platform_role not in ["owner", "editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization administrators can configure SSO."},
        )

    if body.provider_type not in ["oidc", "saml"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_TYPE", "message": "Provider type must be 'oidc' or 'saml'."},
        )

    domain_dal = DomainDAL(db)
    # Check domain verification before enforcing SSO
    if body.enforce_sso:
        claims = await domain_dal.list_for_org(org_id)
        verified = [c for c in claims if c.status == "verified"]
        if not verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "SSO_DOMAIN_NOT_VERIFIED",
                    "message": "Cannot enforce SSO without at least one verified email domain. Please verify a domain first.",
                },
            )

    idp_dal = IdpDAL(db)
    idp = await idp_dal.upsert_idp(
        org_id=org_id,
        provider_type=body.provider_type,
        is_active=body.is_active,
        enforce_sso=body.enforce_sso,
        session_lifetime_seconds=body.session_lifetime_seconds,
        oidc_issuer_url=body.oidc_issuer_url,
        oidc_client_id=body.oidc_client_id,
        oidc_client_secret=body.oidc_client_secret,
        oidc_discovery_url=body.oidc_discovery_url,
        oidc_scopes=body.oidc_scopes,
        saml_entity_id=body.saml_entity_id,
        saml_sso_url=body.saml_sso_url,
        saml_slo_url=body.saml_slo_url,
        saml_x509_cert=body.saml_x509_cert,
        saml_sp_entity_id=body.saml_sp_entity_id,
        saml_acs_url=body.saml_acs_url,
    )
    await db.commit()

    return IdpConfigResponse(
        id=str(idp.id),
        organization_id=str(idp.organization_id),
        provider_type=idp.provider_type,
        is_active=idp.is_active,
        enforce_sso=idp.enforce_sso,
        session_lifetime_seconds=idp.session_lifetime_seconds,
        oidc_issuer_url=idp.oidc_issuer_url,
        oidc_client_id=idp.oidc_client_id,
        oidc_discovery_url=idp.oidc_discovery_url,
        oidc_scopes=idp.oidc_scopes,
        saml_entity_id=idp.saml_entity_id,
        saml_sso_url=idp.saml_sso_url,
        saml_slo_url=idp.saml_slo_url,
        saml_sp_entity_id=idp.saml_sp_entity_id,
        saml_acs_url=idp.saml_acs_url,
        created_at=idp.created_at.isoformat(),
        updated_at=idp.updated_at.isoformat(),
    )


@router.get("/organizations/{org_id}/sso/idp", response_model=Optional[IdpConfigResponse])
async def get_idp_config(
    org_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Returns the current SSO IdP configuration for the organization."""
    if user.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Access denied."},
        )

    idp_dal = IdpDAL(db)
    idp = await idp_dal.get_by_org(org_id)
    if not idp:
        return None

    return IdpConfigResponse(
        id=str(idp.id),
        organization_id=str(idp.organization_id),
        provider_type=idp.provider_type,
        is_active=idp.is_active,
        enforce_sso=idp.enforce_sso,
        session_lifetime_seconds=idp.session_lifetime_seconds,
        oidc_issuer_url=idp.oidc_issuer_url,
        oidc_client_id=idp.oidc_client_id,
        oidc_discovery_url=idp.oidc_discovery_url,
        oidc_scopes=idp.oidc_scopes,
        saml_entity_id=idp.saml_entity_id,
        saml_sso_url=idp.saml_sso_url,
        saml_slo_url=idp.saml_slo_url,
        saml_sp_entity_id=idp.saml_sp_entity_id,
        saml_acs_url=idp.saml_acs_url,
        created_at=idp.created_at.isoformat(),
        updated_at=idp.updated_at.isoformat(),
    )


# ==========================================
# SAML SP Metadata
# ==========================================

@router.get("/auth/sso/saml/metadata")
async def get_saml_metadata(
    sp_entity_id: str = Query("urn:capsule:sp"),
    acs_url: str = Query("http://localhost:8000/v1/auth/sso/saml/callback"),
):
    """Returns standard SAML 2.0 SP Metadata XML."""
    xml_content = _saml_service.generate_sp_metadata(sp_entity_id=sp_entity_id, acs_url=acs_url)
    return Response(content=xml_content, media_type="application/samlmetadata+xml")


# ==========================================
# SSO Flow Initiation & Callbacks
# ==========================================

@router.get("/auth/sso/login")
async def sso_login(
    org_slug: str = Query(...),
    target_app: Optional[str] = Query(None),
    return_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Dispatches to corporate IdP login screen (OIDC authorization endpoint or SAML AuthnRequest).
    """
    org_dal = OrganizationDAL(db)
    org = await org_dal.get_by_slug(org_slug)
    if not org or org.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": f"Organization '{org_slug}' not found or inactive."},
        )

    idp_dal = IdpDAL(db)
    idp = await idp_dal.get_by_org(org.id)
    if not idp or not idp.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "SSO_NOT_CONFIGURED", "message": f"SSO is not configured for organization '{org_slug}'."},
        )

    if idp.provider_type == "oidc":
        disc_url = idp.oidc_discovery_url or (f"{idp.oidc_issuer_url.rstrip('/')}/.well-known/openid-configuration" if idp.oidc_issuer_url else None)
        if not disc_url:
            raise HTTPException(status_code=500, detail="Missing OIDC discovery URL")

        doc = await _oidc_service.discover(disc_url)
        auth_endpoint = doc.get("authorization_endpoint")
        if not auth_endpoint:
            raise HTTPException(status_code=500, detail="OIDC discovery doc missing authorization_endpoint")

        state_token, nonce = _oidc_service.generate_state_and_nonce(
            org_id=org.id,
            target_app=target_app,
            return_to=return_to,
        )

        scopes = "+".join(idp.oidc_scopes or ["openid", "email", "profile"])
        redirect_uri = "http://localhost:8000/v1/auth/sso/oidc/callback"
        auth_url = (
            f"{auth_endpoint}?response_type=code"
            f"&client_id={idp.oidc_client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scopes}"
            f"&state={state_token}"
            f"&nonce={nonce}"
        )
        return RedirectResponse(url=auth_url, status_code=302)

    elif idp.provider_type == "saml":
        if not idp.saml_sso_url:
            raise HTTPException(status_code=500, detail="Missing SAML SSO URL in IdP configuration.")

        acs_url = idp.saml_acs_url or "http://localhost:8000/v1/auth/sso/saml/callback"
        req_id, b64_req = _saml_service.generate_authn_request(
            sp_entity_id=idp.saml_sp_entity_id or "urn:capsule:sp",
            acs_url=acs_url,
            idp_sso_url=idp.saml_sso_url,
        )

        # Encode context in RelayState
        relay_payload = {
            "org_id": str(org.id),
            "target_app": target_app,
            "return_to": return_to,
            "req_id": req_id,
            "iat": int(datetime.now(timezone.utc).timestamp()),
        }
        secret = os.environ.get("JWT_SECRET", DEFAULT_SECRET)
        relay_state = jwt.encode(relay_payload, secret, algorithm="HS256")

        redirect_url = f"{idp.saml_sso_url}?SAMLRequest={b64_req}&RelayState={relay_state}"
        return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/auth/sso/oidc/callback")
async def oidc_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Handles OIDC Authorization Code callback: verifies state, exchanges code,
    validates ID token signature & nonce, JIT provisions user, and issues app ticket.
    """
    try:
        state_payload = _oidc_service.verify_state(state)
    except OIDCError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_STATE", "message": str(e)},
        )

    org_id = uuid.UUID(state_payload["org_id"])
    target_app = state_payload.get("target_app") or "leave-tracker"
    return_to = state_payload.get("return_to") or "/"
    expected_nonce = state_payload["nonce"]

    idp_dal = IdpDAL(db)
    idp = await idp_dal.get_by_org_and_type(org_id, "oidc")
    if not idp or not idp.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "SSO_INACTIVE", "message": "OIDC Identity Provider is not active."},
        )

    disc_url = idp.oidc_discovery_url or f"{idp.oidc_issuer_url.rstrip('/')}/.well-known/openid-configuration"
    doc = await _oidc_service.discover(disc_url)
    token_endpoint = doc.get("token_endpoint")
    jwks_uri = doc.get("jwks_uri")

    client_secret = await idp_dal.get_decrypted_client_secret(idp)
    redirect_uri = "http://localhost:8000/v1/auth/sso/oidc/callback"

    token_data = await _oidc_service.exchange_code(
        token_endpoint=token_endpoint,
        code=code,
        client_id=idp.oidc_client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )

    id_token = token_data.get("id_token")
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "MISSING_ID_TOKEN", "message": "Token response missing id_token."},
        )

    claims = await _oidc_service.verify_id_token(
        id_token=id_token,
        jwks_uri=jwks_uri,
        expected_issuer=idp.oidc_issuer_url or doc.get("issuer", ""),
        expected_client_id=idp.oidc_client_id,
        expected_nonce=expected_nonce,
        clock_skew_seconds=120,
    )

    email = claims.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "MISSING_EMAIL", "message": "ID token missing email claim."},
        )

    # JIT Provisioning / Update User
    user_dal = UserDAL(db)
    user = await user_dal.get_by_email(email)
    sub = claims.get("sub")
    iss = claims.get("iss")

    if not user:
        user = await user_dal.create(
            email=email,
            display_name=claims.get("name") or email.split("@")[0],
            identity_subject=sub,
            identity_issuer=iss,
            status="active",
        )
        await user_dal.add_to_org(org_id, user.id, platform_role="user")
    else:
        if user.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "USER_DEPROVISIONED", "message": "This account is deprovisioned or suspended."},
            )
        # Check org membership
        members = await user_dal.get_org_members(org_id)
        if not any(m.user_id == user.id for m in members):
            await user_dal.add_to_org(org_id, user.id, platform_role="user")

    await db.commit()

    # Issue platform session ticket
    ticket = _generate_app_ticket(
        user_id=user.id,
        email=user.email,
        org_id=org_id,
        platform_role="user",
        target_app=target_app,
        session_lifetime_seconds=idp.session_lifetime_seconds,
    )

    app_callback_url = f"http://{target_app}.apps.localhost:3000/auth/callback?ticket={ticket}&return_to={return_to}"
    return RedirectResponse(url=app_callback_url, status_code=302)


@router.post("/auth/sso/saml/callback")
async def saml_callback(
    SAMLResponse: str = Form(...),
    RelayState: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Handles SAML 2.0 Assertion Consumer Service (ACS) callback:
    validates cryptographic signature, audience, replay, clock skew, and JIT provisions user.
    """
    if not RelayState:
        raise HTTPException(status_code=400, detail="Missing RelayState parameter.")

    secret = os.environ.get("JWT_SECRET", DEFAULT_SECRET)
    try:
        relay_payload = jwt.decode(RelayState, secret, algorithms=["HS256"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid RelayState: {e}")

    org_id = uuid.UUID(relay_payload["org_id"])
    target_app = relay_payload.get("target_app") or "leave-tracker"
    return_to = relay_payload.get("return_to") or "/"

    idp_dal = IdpDAL(db)
    idp = await idp_dal.get_by_org_and_type(org_id, "saml")
    if not idp or not idp.is_active or not idp.saml_x509_cert:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "SAML_NOT_CONFIGURED", "message": "SAML IdP not configured or inactive."},
        )

    # Validate SAML Response using SAMLService (with DefusedXML and Cryptography RSA verification)
    try:
        parsed = _saml_service.parse_and_validate_response(
            saml_response_b64=SAMLResponse,
            sp_entity_id=idp.saml_sp_entity_id or "urn:capsule:sp",
            acs_url=idp.saml_acs_url,
            idp_x509_cert=idp.saml_x509_cert,
            clock_skew_seconds=120,
        )
    except SAMLError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SAML_VALIDATION_FAILED", "message": str(e)},
        )

    # Replay Protection: Check assertion ID
    replay_dal = ReplayDAL(db)
    assertion_id = parsed["assertion_id"]
    is_recorded = await replay_dal.record_assertion(
        assertion_id=assertion_id,
        org_id=org_id,
        expires_at=parsed["expires_at"],
    )
    if not is_recorded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "REPLAY_ATTACK_DETECTED", "message": "SAML Assertion ID has already been processed."},
        )

    email = parsed["email"]
    sub = parsed["sub"]
    user_dal = UserDAL(db)
    user = await user_dal.get_by_email(email)

    if not user:
        user = await user_dal.create(
            email=email,
            display_name=parsed["display_name"],
            identity_subject=sub,
            identity_issuer=idp.saml_entity_id or "saml",
            status="active",
        )
        await user_dal.add_to_org(org_id, user.id, platform_role="user")
    else:
        if user.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "USER_DEPROVISIONED", "message": "This user account has been deprovisioned."},
            )
        members = await user_dal.get_org_members(org_id)
        if not any(m.user_id == user.id for m in members):
            await user_dal.add_to_org(org_id, user.id, platform_role="user")

    await db.commit()

    ticket = _generate_app_ticket(
        user_id=user.id,
        email=user.email,
        org_id=org_id,
        platform_role="user",
        target_app=target_app,
        session_lifetime_seconds=idp.session_lifetime_seconds,
    )

    app_callback_url = f"http://{target_app}.apps.localhost:3000/auth/callback?ticket={ticket}&return_to={return_to}"
    return RedirectResponse(url=app_callback_url, status_code=302)


@router.post("/auth/sso/logout")
async def sso_logout(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Single Logout (SLO): Immediately revokes user sessions and publish tokens.
    """
    user_dal = UserDAL(db)
    await user_dal.revoke_sessions(user.id)
    await user_dal.revoke_tokens(user.id)
    await db.commit()
    return {"status": "logged_out", "message": "Sessions successfully revoked."}
