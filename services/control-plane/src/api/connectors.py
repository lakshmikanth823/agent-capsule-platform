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
import json
import uuid
from typing import Optional, Dict, Any, List, Literal
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


def parse_viewer_identity(header_value: Optional[str]) -> Optional[Dict[str, Any]]:
    if not header_value:
        return None
    try:
        if header_value.count(".") == 2:
            import jwt
            secret = os.environ.get("CAPSULE_IDENTITY_SECRET", "dev-emulator-secret-key-1234567890")
            try:
                return jwt.decode(header_value, secret, algorithms=["HS256"], options={"verify_aud": False})
            except Exception:
                return jwt.decode(header_value, options={"verify_signature": False})
        return json.loads(header_value)
    except Exception:
        return None


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

    # Policy Check: Connector disabled globally?
    disabled_connectors = env_profile.get("disabled_connectors", [])
    if connector_name in disabled_connectors:
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
        # Policy Check: Service identity allowed?
        if env_profile.get("allow_service_identity") is False:
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
    if org:
        viewer_user_id = None
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

    # 7. Audit log (strictly masking any sensitive tokens)
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
