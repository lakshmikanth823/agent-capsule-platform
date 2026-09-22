"""
Credential Broker API Endpoints
Implements TRD Section 21 & PRD FR-024 / FR-025 / FR-026:
- Applications ask the broker for declared connector capabilities.
- Broker attaches credentials at the egress layer.
- Apps never receive raw credentials.
- Secrets are stored encrypted, never logged, and never returned in API responses.
- Default identity is viewer; service identity requires explicit manifest declaration and org policy permission.
"""
import os
import time
import json
import uuid
from typing import Optional, Dict, Any, List, Literal, Tuple
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.session import get_db_session
from db.dal import AppDAL, OrganizationDAL, ConnectorCredentialDAL, AuditDAL
from db.models import App
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from auth.crypto import mask_sensitive_data
from connectors.registry import get_connector, list_available_connectors

router = APIRouter(tags=["connectors"])


class SetCredentialRequest(BaseModel):
    identity_type: Literal["service", "viewer"] = "service"
    credential: Dict[str, Any]
    user_id: Optional[uuid.UUID] = None
    app_id: Optional[uuid.UUID] = None


class ConnectorCredentialMetadataResponse(BaseModel):
    id: str
    organization_id: str
    connector_name: str
    identity_type: str
    user_id: Optional[str] = None
    app_id: Optional[str] = None
    status: str = "configured"
    updated_at: Optional[str] = None


class SaveConsentRequest(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = 3600
    scope: Optional[str] = "https://www.googleapis.com/auth/spreadsheets.readonly"
    app_id: Optional[uuid.UUID] = None
    organization_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None


class DisconnectConnectorRequest(BaseModel):
    organization_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None


def parse_viewer_identity(header_value: Optional[str]) -> Optional[Dict[str, Any]]:
    if not header_value:
        return None
    try:
        if header_value.count(".") == 2:
            import jwt
            secret = os.environ.get("CAPSULE_IDENTITY_SECRET", "dev-emulator-secret-key-1234567890")
            # Strictly require valid HMAC-SHA256 signature; do NOT fall back to unsigned decode
            return jwt.decode(header_value, secret, algorithms=["HS256"], options={"verify_aud": False})

        # In hermetic test or emulator mode only, permit JSON strings for mock caller fixtures
        import sys
        is_test_mode = (
            os.environ.get("CAPSULE_EMULATOR") == "true"
            or os.environ.get("TESTING") == "true"
            or "pytest" in sys.modules
        )
        if is_test_mode and header_value.strip().startswith("{"):
            return json.loads(header_value)

        return None
    except Exception:
        return None


async def _resolve_user_and_org(
    authorization: Optional[str] = None,
    x_capsule_identity: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    organization_id: Optional[uuid.UUID] = None,
    db: Optional[AsyncSession] = None,
) -> Tuple[Optional[uuid.UUID], Optional[uuid.UUID]]:
    """Resolves user_id and organization_id from Bearer token, x-capsule-identity, or explicit params."""
    if authorization and authorization.startswith("Bearer ") and db:
        try:
            user = await get_current_user(authorization=authorization, db=db)
            if user:
                return user.id, user.organization_id
        except Exception:
            pass

    if x_capsule_identity:
        ident = parse_viewer_identity(x_capsule_identity)
        if ident:
            u_id = None
            o_id = None
            if ident.get("sub"):
                try:
                    u_id = uuid.UUID(ident["sub"])
                except Exception:
                    pass
            if ident.get("org_id"):
                try:
                    o_id = uuid.UUID(ident["org_id"])
                except Exception:
                    pass
            return u_id or user_id, o_id or organization_id

    return user_id, organization_id


@router.post("/connectors/{connector_name}/invoke")
async def invoke_connector(
    connector_name: str,
    payload: Dict[str, Any],
    x_capsule_key: Optional[str] = Header(None, alias="x-capsule-key"),
    x_capsule_id: Optional[str] = Header(None, alias="x-capsule-id"),
    x_capsule_identity: Optional[str] = Header(None, alias="x-capsule-identity"),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Invokes a declared connector capability.
    The broker verifies declarations, enforces identity & org policy, attaches credentials,
    and returns the result without leaking credentials to the calling app.
    """
    app_dal = AppDAL(db)
    org_dal = OrganizationDAL(db)
    cred_dal = ConnectorCredentialDAL(db)
    audit_dal = AuditDAL(db)

    # 1. Resolve calling app
    app: Optional[App] = None
    if x_capsule_id:
        try:
            app = await app_dal.get_by_id(uuid.UUID(x_capsule_id))
        except ValueError:
            pass
    elif x_capsule_key:
        # Search app by key
        result = await db.execute(select(App).where(App.app_key == x_capsule_key))
        app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "APP_IDENTIFICATION_REQUIRED",
                "message": "Missing or invalid app identification header ('x-capsule-key' or 'x-capsule-id').",
            },
        )

    if app.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "APP_NOT_ACTIVE", "message": f"App '{app.app_key}' is not active."},
        )

    # 2. Check connector capability declaration in manifest
    manifest = app.manifest or {}
    declared_connectors = manifest.get("capabilities", {}).get("connectors", [])

    matched_declaration = None
    if isinstance(declared_connectors, list):
        for c in declared_connectors:
            if isinstance(c, str) and c == connector_name:
                matched_declaration = {"name": c, "acts_as": "viewer"}
                break
            elif isinstance(c, dict) and c.get("name") == connector_name:
                matched_declaration = c
                break
    elif isinstance(declared_connectors, dict):
        if connector_name in declared_connectors:
            val = declared_connectors[connector_name]
            matched_declaration = val if isinstance(val, dict) else {"name": connector_name, "acts_as": "viewer"}

    if not matched_declaration:
        await audit_dal.record_event(
            action="connector.invoke",
            outcome="denied",
            organization_id=app.organization_id,
            app_id=app.id,
            target_type="connector",
            metadata={
                "connector": connector_name,
                "reason": "Capability not declared in manifest",
                "masked_payload": mask_sensitive_data(payload),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CAPABILITY_DENIED",
                "message": f"Capsule '{app.app_key}' has not declared connector capability: '{connector_name}'.",
            },
        )

    # 3. Determine identity mode: default is 'viewer'
    acts_as = matched_declaration.get("acts_as") or matched_declaration.get("identity") or "viewer"

    # Fetch organization and environment profile
    org = await org_dal.get_by_id(app.organization_id) if app.organization_id else None
    env_profile = org.environment_profile if org and org.environment_profile else {}

    # Policy Check: Connector disabled globally or excluded from allowlist?
    conn_policy = env_profile.get("capabilities", {}).get("connectors", {}) if isinstance(env_profile.get("capabilities"), dict) else (env_profile.get("connectors") or {})
    disabled_connectors = conn_policy.get("disabled_connectors") or env_profile.get("disabled_connectors", [])
    allowed_connectors = conn_policy.get("allowed_connectors") or env_profile.get("allowed_connectors", ["*"])
    allow_service = conn_policy.get("allow_service_identity") if "allow_service_identity" in conn_policy else env_profile.get("allow_service_identity", True)
    identity_rules = conn_policy.get("connector_identity_rules", {})

    if connector_name in disabled_connectors or ("*" not in allowed_connectors and connector_name not in allowed_connectors):
        await audit_dal.record_event(
            action="connector.invoke",
            outcome="denied",
            organization_id=app.organization_id,
            app_id=app.id,
            target_type="connector",
            metadata={"connector": connector_name, "reason": "Connector disabled by organization policy"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CONNECTOR_DISABLED",
                "message": f"Connector '{connector_name}' is prohibited by organization policy.",
            },
        )

    viewer_context = None
    if acts_as == "service":
        permitted = ["viewer", "service"]
        if connector_name in identity_rules:
            permitted = identity_rules[connector_name].get("allowed_identities", ["viewer"])
        elif connector_name in ("sheets.read", "google_sheets.read"):
            permitted = ["viewer"]

        if not allow_service or "service" not in permitted:
            await audit_dal.record_event(
                action="connector.invoke",
                outcome="denied",
                organization_id=app.organization_id,
                app_id=app.id,
                target_type="connector",
                metadata={"connector": connector_name, "reason": "Service identity prohibited by organization policy"},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SERVICE_IDENTITY_FORBIDDEN",
                    "message": f"Organization policy prohibits service identity for connector '{connector_name}'.",
                },
            )
    else:
        # acts_as == 'viewer': requires signed viewer identity
        viewer_context = parse_viewer_identity(x_capsule_identity)
        if not viewer_context:
            await audit_dal.record_event(
                action="connector.invoke",
                outcome="denied",
                organization_id=app.organization_id,
                app_id=app.id,
                target_type="connector",
                metadata={"connector": connector_name, "reason": "Missing required viewer identity"},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "VIEWER_IDENTITY_REQUIRED",
                    "message": f"Connector '{connector_name}' executes as viewer, but no valid 'x-capsule-identity' header was provided.",
                },
            )

    # 4. Resolve credential from secure encrypted store
    credential = None
    viewer_user_id = None
    if org:
        if viewer_context and viewer_context.get("sub"):
            try:
                viewer_user_id = uuid.UUID(viewer_context["sub"])
            except ValueError:
                pass

        if acts_as == "viewer" and viewer_user_id:
            # First attempt viewer-specific credential
            credential = await cred_dal.get_credential(org.id, connector_name, "viewer", viewer_user_id)

        # If not found or service identity, fetch org-level credential
        if not credential:
            credential = await cred_dal.get_credential(org.id, connector_name, acts_as)

    if not credential:
        await audit_dal.record_event(
            action="connector.invoke",
            outcome="denied",
            organization_id=app.organization_id,
            app_id=app.id,
            target_type="connector",
            metadata={"connector": connector_name, "reason": "Credentials not configured"},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CREDENTIAL_NOT_CONFIGURED",
                "message": f"No credentials configured for connector '{connector_name}' under identity '{acts_as}'.",
            },
        )

    # 5. Resolve connector implementation
    connector = get_connector(connector_name)
    if not connector:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONNECTOR_NOT_FOUND",
                "message": f"Connector implementation '{connector_name}' is not supported by the platform.",
            },
        )

    # 6. Execute connector invocation at egress layer
    try:
        result = await connector.invoke(
            payload=payload,
            credential=credential,
            identity=viewer_context,
            context=matched_declaration,
        )
    except Exception as exc:
        await audit_dal.record_event(
            action="connector.invoke",
            outcome="failed",
            organization_id=app.organization_id,
            app_id=app.id,
            target_type="connector",
            metadata={"connector": connector_name, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "CONNECTOR_INVOCATION_FAILED",
                "message": f"Connector execution failed: {str(exc)}",
            },
        )

    # 7. Check if invocation result indicates failure
    if isinstance(result, dict) and result.get("status") == "failed":
        code = result.get("code") or "CONNECTOR_INVOCATION_FAILED"
        err_msg = result.get("error") or "Connector invocation failed"

        if code in ("SPREADSHEET_NOT_ALLOWED", "PERMISSION_DENIED"):
            http_status = status.HTTP_403_FORBIDDEN
        elif code == "OAUTH_TOKEN_REVOKED":
            http_status = status.HTTP_401_UNAUTHORIZED
        elif code == "NOT_FOUND":
            http_status = status.HTTP_404_NOT_FOUND
        else:
            http_status = status.HTTP_400_BAD_REQUEST

        await audit_dal.record_event(
            action="connector.invoke",
            outcome="denied" if http_status == 403 else "failed",
            organization_id=app.organization_id,
            app_id=app.id,
            target_type="connector",
            metadata={"connector": connector_name, "code": code, "error": err_msg},
        )

        raise HTTPException(
            status_code=http_status,
            detail={
                "code": code,
                "message": err_msg,
                **{k: v for k, v in result.items() if k not in ("status", "code", "error")},
            },
        )

    # 8. Persist refreshed token if updated in-place during invoke
    if isinstance(credential, dict) and credential.pop("_refreshed", False):
        if acts_as == "viewer" and viewer_user_id and org:
            await cred_dal.set_credential(
                organization_id=org.id,
                connector_name=connector_name,
                identity_type="viewer",
                credential_data=credential,
                user_id=viewer_user_id,
                app_id=app.id,
            )

    # 9. Audit log (strictly masking any sensitive tokens)
    await audit_dal.record_event(
        action="connector.invoke",
        outcome="success",
        organization_id=app.organization_id,
        app_id=app.id,
        target_type="connector",
        metadata={
            "connector": connector_name,
            "identity_type": acts_as,
            "masked_payload": mask_sensitive_data(payload),
        },
    )

    # Return result (guaranteeing masked / safe output)
    return mask_sensitive_data(result)


@router.post(
    "/organizations/{org_id}/connectors/{connector_name}/credentials",
    response_model=ConnectorCredentialMetadataResponse,
)
async def set_connector_credential(
    org_id: uuid.UUID,
    connector_name: str,
    req: SetCredentialRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Admin endpoint: Stores or updates encrypted connector credentials.
    Returns metadata only. The secret is NEVER returned in the response or logs.
    """
    if current_user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization owner or editor can configure connector credentials."},
        )

    cred_dal = ConnectorCredentialDAL(db)
    audit_dal = AuditDAL(db)

    cred = await cred_dal.set_credential(
        organization_id=org_id,
        connector_name=connector_name,
        identity_type=req.identity_type,
        credential_data=req.credential,
        user_id=req.user_id,
        app_id=req.app_id,
    )

    await audit_dal.record_event(
        action="connector.credential.configure",
        outcome="success",
        organization_id=org_id,
        actor_user_id=current_user.id,
        target_type="connector_credential",
        target_id=cred.id,
        metadata={
            "connector_name": connector_name,
            "identity_type": req.identity_type,
        },
    )

    return ConnectorCredentialMetadataResponse(
        id=str(cred.id),
        organization_id=str(cred.organization_id),
        connector_name=cred.connector_name,
        identity_type=cred.identity_type,
        user_id=str(cred.user_id) if cred.user_id else None,
        app_id=str(cred.app_id) if cred.app_id else None,
        status="configured",
        updated_at=cred.updated_at.isoformat() if cred.updated_at else None,
    )


@router.get("/organizations/{org_id}/connectors")
async def list_configured_connectors(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Lists configured connectors for an organization (metadata only, no secrets).
    """
    cred_dal = ConnectorCredentialDAL(db)
    metadata_list = await cred_dal.list_credentials_metadata(org_id)
    return {
        "organization_id": str(org_id),
        "connectors": metadata_list,
        "available_connectors": list_available_connectors(),
    }


@router.delete("/organizations/{org_id}/connectors/{connector_name}/credentials")
async def delete_connector_credential(
    org_id: uuid.UUID,
    connector_name: str,
    identity_type: Literal["service", "viewer"] = "service",
    user_id: Optional[uuid.UUID] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Deletes a connector credential.
    """
    if current_user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization owner or editor can delete connector credentials."},
        )

    cred_dal = ConnectorCredentialDAL(db)
    audit_dal = AuditDAL(db)

    deleted = await cred_dal.delete_credential(org_id, connector_name, identity_type, user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Connector credential not found."},
        )

    await audit_dal.record_event(
        action="connector.credential.delete",
        outcome="success",
        organization_id=org_id,
        actor_user_id=current_user.id,
        target_type="connector_credential",
        metadata={"connector_name": connector_name, "identity_type": identity_type},
    )

    return {"status": "deleted", "connector_name": connector_name, "identity_type": identity_type}


@router.get("/connectors/{connector_name}/consent")
async def get_connector_consent_status(
    connector_name: str,
    app_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
    organization_id: Optional[uuid.UUID] = None,
    x_capsule_identity: Optional[str] = Header(None, alias="x-capsule-identity"),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Returns consent status and required permissions for a viewer-identity connector.
    """
    app_dal = AppDAL(db)
    cred_dal = ConnectorCredentialDAL(db)

    resolved_user_id, resolved_org_id = await _resolve_user_and_org(
        authorization=authorization,
        x_capsule_identity=x_capsule_identity,
        user_id=user_id,
        organization_id=organization_id,
        db=db,
    )

    allowed_spreadsheets = None
    if app_id:
        try:
            app = await app_dal.get_by_id(app_id)
            if app:
                if not resolved_org_id:
                    resolved_org_id = app.organization_id
                manifest = app.manifest or {}
                conns = manifest.get("capabilities", {}).get("connectors", [])
                if isinstance(conns, list):
                    for c in conns:
                        if isinstance(c, dict) and c.get("name") == connector_name:
                            allowed_spreadsheets = c.get("spreadsheet_ids")
                            break
        except Exception:
            pass

    consented = False
    if resolved_org_id and resolved_user_id:
        cred = await cred_dal.get_credential(resolved_org_id, connector_name, "viewer", resolved_user_id)
        if cred and (cred.get("access_token") or cred.get("refresh_token")):
            consented = True

    required_scopes = []
    if connector_name in ("sheets.read", "google_sheets.read"):
        required_scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

    return {
        "connector_name": connector_name,
        "consented": consented,
        "status": "connected" if consented else "not_connected",
        "acts_as": "viewer",
        "required_scopes": required_scopes,
        "allowed_spreadsheets": allowed_spreadsheets,
        "user_id": str(resolved_user_id) if resolved_user_id else None,
        "organization_id": str(resolved_org_id) if resolved_org_id else None,
    }


@router.post("/connectors/{connector_name}/consent")
async def grant_connector_consent(
    connector_name: str,
    req: SaveConsentRequest,
    authorization: Optional[str] = Header(None),
    x_capsule_identity: Optional[str] = Header(None, alias="x-capsule-identity"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Saves viewer OAuth credentials encrypted at rest following consent grant.
    Tokens are strictly per-user and never exposed to the application.
    """
    app_dal = AppDAL(db)
    cred_dal = ConnectorCredentialDAL(db)
    audit_dal = AuditDAL(db)

    resolved_user_id, resolved_org_id = await _resolve_user_and_org(
        authorization=authorization,
        x_capsule_identity=x_capsule_identity,
        user_id=req.user_id,
        organization_id=req.organization_id,
        db=db,
    )

    if req.app_id and not resolved_org_id:
        app = await app_dal.get_by_id(req.app_id)
        if app:
            resolved_org_id = app.organization_id

    if not resolved_org_id or not resolved_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "IDENTITY_REQUIRED", "message": "user_id and organization_id are required to store viewer consent."},
        )

    now = time.time()
    credential_data = {
        "access_token": req.access_token,
        "refresh_token": req.refresh_token,
        "expires_at": now + (req.expires_in or 3600),
        "scope": req.scope or "https://www.googleapis.com/auth/spreadsheets.readonly",
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", "mock-client-id"),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", "mock-client-secret"),
    }

    cred = await cred_dal.set_credential(
        organization_id=resolved_org_id,
        connector_name=connector_name,
        identity_type="viewer",
        credential_data=credential_data,
        user_id=resolved_user_id,
        app_id=req.app_id,
    )

    await audit_dal.record_event(
        action="connector.consent.granted",
        outcome="success",
        organization_id=resolved_org_id,
        actor_user_id=resolved_user_id,
        target_type="connector_credential",
        target_id=cred.id,
        metadata={"connector_name": connector_name, "scope": req.scope},
    )

    return {
        "status": "consented",
        "connector_name": connector_name,
        "identity_type": "viewer",
        "user_id": str(resolved_user_id),
        "organization_id": str(resolved_org_id),
    }


@router.post("/connectors/{connector_name}/disconnect")
async def disconnect_connector(
    connector_name: str,
    req: Optional[DisconnectConnectorRequest] = None,
    authorization: Optional[str] = Header(None),
    x_capsule_identity: Optional[str] = Header(None, alias="x-capsule-identity"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Disconnects a user's connector account and removes their encrypted tokens.
    """
    cred_dal = ConnectorCredentialDAL(db)
    audit_dal = AuditDAL(db)

    req_user_id = req.user_id if req else None
    req_org_id = req.organization_id if req else None

    resolved_user_id, resolved_org_id = await _resolve_user_and_org(
        authorization=authorization,
        x_capsule_identity=x_capsule_identity,
        user_id=req_user_id,
        organization_id=req_org_id,
        db=db,
    )

    if not resolved_org_id or not resolved_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "IDENTITY_REQUIRED", "message": "user_id and organization_id are required to disconnect connector."},
        )

    deleted = await cred_dal.delete_credential(
        organization_id=resolved_org_id,
        connector_name=connector_name,
        identity_type="viewer",
        user_id=resolved_user_id,
    )

    await audit_dal.record_event(
        action="connector.consent.revoked",
        outcome="success",
        organization_id=resolved_org_id,
        actor_user_id=resolved_user_id,
        target_type="connector_credential",
        metadata={"connector_name": connector_name},
    )

    return {
        "status": "disconnected",
        "connector_name": connector_name,
        "deleted": deleted,
    }


@router.delete("/organizations/{org_id}/users/{user_id}/connector-tokens")
async def deprovision_user_connector_tokens(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Admin endpoint: Deprovisions all connector tokens stored for a user in the organization.
    """
    if current_user.platform_role not in ("owner", "editor") and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only organization owner/editor or the user can deprovision tokens."},
        )

    cred_dal = ConnectorCredentialDAL(db)
    audit_dal = AuditDAL(db)

    deleted_count = await cred_dal.delete_all_credentials_for_user(org_id, user_id)

    await audit_dal.record_event(
        action="connector.tokens.deprovisioned",
        outcome="success",
        organization_id=org_id,
        actor_user_id=current_user.id,
        target_type="user",
        target_id=user_id,
        metadata={"deleted_count": deleted_count},
    )

    return {
        "status": "deprovisioned",
        "organization_id": str(org_id),
        "user_id": str(user_id),
        "deleted_count": deleted_count,
    }
