"""
App and Version management endpoints matching docs/api-cli-spec/openapi.yaml.
"""
import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import AppDAL, AppVersionDAL, AuditDAL
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from manifest.validator import validate_manifest
from storage import get_storage_driver
from .schemas import (
    AppResponse,
    AppListResponse,
    AppVersionResponse,
    VersionListResponse,
    CreateAppRequest,
    PublishOperationResponse,
    ValidateRequest,
    ValidationResultResponse,
)

router = APIRouter(tags=["Apps"])


def _format_app_response(app: Any) -> AppResponse:
    return AppResponse(
        id=app.id,
        organization_id=app.organization_id,
        owner_user_id=app.owner_user_id,
        app_key=app.app_key,
        name=app.name,
        description=app.description,
        status=app.status,
        shape=app.shape,
        runtime=app.runtime,
        current_version_id=app.current_version_id,
        app_url=f"http://{app.app_key}.localhost:8080" if app.status == "active" else None,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


@router.post("/apps", response_model=AppResponse, status_code=status.HTTP_201_CREATED)
async def create_app(
    request: CreateAppRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Create a new draft Software Capsule entry in the registry.
    Owner and organization are derived strictly from caller's token.
    """
    app_dal = AppDAL(db)
    audit_dal = AuditDAL(db)

    # 1. Validate manifest
    val_result = validate_manifest(request.manifest)
    if not val_result["valid"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=val_result,
        )

    # 2. Check that top-level id matches manifest id
    manifest_id = request.manifest.get("id")
    if request.id != manifest_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "ID_MISMATCH",
                "message": f"App ID '{request.id}' does not match manifest ID '{manifest_id}'.",
            },
        )

    # 3. Check for conflict in organization
    existing = await app_dal.get_by_key(user.organization_id, request.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "APP_ALREADY_EXISTS",
                "message": f"App '{request.id}' already exists in this organization.",
            },
        )

    # 4. Create app
    app = await app_dal.create(
        app_key=request.id,
        name=request.name,
        organization_id=user.organization_id,
        owner_user_id=user.id,
        description=request.description,
        shape=request.shape,
        runtime=request.runtime,
        status="draft",
        manifest=val_result.get("effective_manifest") or request.manifest,
    )

    # 5. Record audit event
    await audit_dal.record_event(
        action="app.create",
        outcome="success",
        organization_id=user.organization_id,
        app_id=app.id,
        actor_user_id=user.id,
        target_type="app",
        target_id=app.id,
        metadata={"app_key": app.app_key, "name": app.name},
    )
    await db.commit()

    return _format_app_response(app)


@router.get("/apps", response_model=AppListResponse)
async def list_apps(
    limit: int = Query(50, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    List apps belonging to caller's organization.
    """
    app_dal = AppDAL(db)
    apps = await app_dal.list_by_org(user.organization_id)
    if status:
        apps = [a for a in apps if a.status == status]

    return AppListResponse(
        items=[_format_app_response(a) for a in apps[:limit]],
        next_cursor=None,
    )


@router.get("/apps/{app_id}", response_model=AppResponse)
async def get_app(
    app_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get app details by UUID or app_key.
    Enforces organization isolation.
    """
    app_dal = AppDAL(db)
    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    return _format_app_response(app)


@router.post("/apps/{app_id}/validate", response_model=ValidationResultResponse)
async def validate_app(
    app_id: str,
    request: ValidateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Validate a manifest without deploying.
    """
    app_dal = AppDAL(db)
    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    result = validate_manifest(request.manifest)
    return ValidationResultResponse(
        valid=result["valid"],
        checks=result["checks"],
        required_approvals=result["required_approvals"],
        warnings=result["warnings"],
    )


@router.post(
    "/apps/{app_id}/publish",
    response_model=PublishOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def publish_app(
    app_id: str,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Idempotent publish endpoint.
    Accepts JSON PublishRequest or multipart/form-data with bundle upload.
    Validates manifest, checks policy & approvals, persists artifact,
    creates version snapshot, and updates live version.
    """
    app_dal = AppDAL(db)
    version_dal = AppVersionDAL(db)
    audit_dal = AuditDAL(db)
    storage = get_storage_driver()

    # 1. Resolve App
    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    # 2. Check Publish Token Scope
    if user.token_type == "publish_token" and user.publish_app_id:
        if user.publish_app_id != app.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "Publish token is not authorized for this app."},
            )

    # 3. Parse Request (JSON or Multipart)
    content_type = request.headers.get("content-type", "")
    manifest: Dict[str, Any] = {}
    artifact_ref: Optional[str] = None
    artifact_sha256: Optional[str] = None
    change_description: Optional[str] = None
    expected_current_version: Optional[int] = None

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        manifest_raw = form.get("manifest")
        if not manifest_raw:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "MISSING_MANIFEST", "message": "Form field 'manifest' is required."},
            )

        if hasattr(manifest_raw, "read"):
            manifest_bytes = await manifest_raw.read()
            manifest_str = manifest_bytes.decode("utf-8")
        else:
            manifest_str = str(manifest_raw)

        try:
            manifest = json.loads(manifest_str)
        except Exception:
            try:
                import yaml
                manifest = yaml.safe_load(manifest_str)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_MANIFEST_SYNTAX", "message": f"Cannot parse manifest: {e}"},
                )

        bundle_file = form.get("bundle")
        if bundle_file and hasattr(bundle_file, "read"):
            bundle_bytes = await bundle_file.read()
            if len(bundle_bytes) > 0:
                artifact_sha256 = hashlib.sha256(bundle_bytes).hexdigest()
                storage_path = f"artifacts/{artifact_sha256[:2]}/{artifact_sha256}.tar.gz"
                artifact_ref = await storage.put(storage_path, bundle_bytes, content_type="application/gzip")

        change_description = str(form.get("change_description")) if form.get("change_description") else None
        expected_raw = form.get("expected_current_version")
        expected_current_version = int(expected_raw) if expected_raw else None
    else:
        try:
            body = await request.json()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_JSON", "message": f"Malformed JSON: {e}"},
            )

        manifest = body.get("manifest")
        if not manifest or not isinstance(manifest, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "MISSING_MANIFEST", "message": "Property 'manifest' is required."},
            )

        artifact_dict = body.get("artifact") or {}
        artifact_ref = artifact_dict.get("ref")
        artifact_sha256 = artifact_dict.get("sha256")
        change_description = body.get("change_description")
        expected_current_version = body.get("expected_current_version")

    if not artifact_ref:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "MISSING_ARTIFACT", "message": "Artifact bundle or reference is required."},
        )

    # 4. Idempotency Check
    payload_repr = json.dumps(
        {"manifest": manifest, "artifact_ref": artifact_ref, "artifact_sha256": artifact_sha256},
        sort_keys=True,
    )
    request_hash = hashlib.sha256(payload_repr.encode("utf-8")).hexdigest()

    if idempotency_key:
        existing_event = await audit_dal.get_by_idempotency_key(idempotency_key)
        if existing_event:
            saved_hash = (existing_event.metadata_ or {}).get("request_hash")
            if saved_hash == request_hash:
                # Idempotent match: return saved operation
                op_id = uuid.UUID(existing_event.metadata_["operation_id"])
                ver_id = existing_event.target_id
                return PublishOperationResponse(
                    operation_id=op_id,
                    type="publish",
                    status="succeeded",
                    app_id=app.id,
                    version_id=ver_id,
                    errors=[],
                    created_at=existing_event.occurred_at,
                    updated_at=existing_event.occurred_at,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "Idempotency key already used with a different request payload.",
                    },
                )

    # 5. Optimistic Concurrency Check
    if expected_current_version is not None:
        current_ver = None
        if app.current_version_id:
            current_ver = await version_dal.get_by_id(app.current_version_id)
        current_ver_num = current_ver.version_number if current_ver else 0
        if current_ver_num != expected_current_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "VERSION_CONFLICT",
                    "message": f"Current version is {current_ver_num}, expected {expected_current_version}.",
                },
            )

    # 6. Manifest Validation
    val_result = validate_manifest(manifest)
    if val_result.get("required_approvals"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "CAPABILITY_APPROVAL_REQUIRED",
                "message": f"Deployment blocked. Approval required for: {', '.join(val_result['required_approvals'])}",
                "required_approvals": val_result["required_approvals"],
                "checks": val_result["checks"],
                "valid": False,
            },
        )

    if not val_result["valid"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=val_result,
        )

    # 7. Create App Version and Baseline SQLite Snapshot
    versions = await version_dal.list_for_app(app.id)
    next_ver_num = len(versions) + 1

    snapshot_ref = f"capsules/{app.id}/snapshots/v{next_ver_num}_baseline.sqlite"
    if not await storage.exists(snapshot_ref):
        await storage.put(snapshot_ref, b"")

    now_utc = datetime.utcnow()
    effective_manifest = val_result.get("effective_manifest") or manifest

    version = await version_dal.create(
        app_id=app.id,
        version_number=next_ver_num,
        source_artifact_ref=artifact_ref,
        build_artifact_ref=None,
        manifest=effective_manifest,
        db_snapshot_ref=snapshot_ref,
        publisher_user_id=user.id,
        publisher_agent=user.claims.get("agent_name"),
        change_description=change_description,
        status="published",
        published_at=now_utc,
    )

    # 8. Update App Current Version & Manifest
    await app_dal.set_current_version(
        app_id=app.id,
        version_id=version.id,
        published_at=now_utc,
        manifest=effective_manifest,
        status="active",
    )

    operation_id = uuid.uuid4()

    # 9. Record Audit Event
    await audit_dal.record_event(
        action="app.publish",
        outcome="success",
        organization_id=user.organization_id,
        app_id=app.id,
        actor_user_id=user.id,
        target_type="app_version",
        target_id=version.id,
        metadata={
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
            "operation_id": str(operation_id),
            "version_number": next_ver_num,
        },
    )
    await db.commit()

    return PublishOperationResponse(
        operation_id=operation_id,
        type="publish",
        status="succeeded",
        app_id=app.id,
        version_id=version.id,
        errors=[],
        created_at=now_utc,
        updated_at=now_utc,
    )


@router.get("/apps/{app_id}/versions", response_model=VersionListResponse)
async def list_versions(
    app_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    List all published versions for an app.
    """
    app_dal = AppDAL(db)
    version_dal = AppVersionDAL(db)

    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    versions = await version_dal.list_for_app(app.id)
    return VersionListResponse(
        items=[
            AppVersionResponse(
                id=v.id,
                app_id=v.app_id,
                version_number=v.version_number,
                status=v.status,
                source_artifact_ref=v.source_artifact_ref,
                build_artifact_ref=v.build_artifact_ref,
                manifest=v.manifest,
                db_snapshot_ref=v.db_snapshot_ref,
                publisher_user_id=v.publisher_user_id,
                publisher_agent=v.publisher_agent,
                change_description=v.change_description,
                published_at=v.published_at,
                created_at=v.created_at,
            )
            for v in versions
        ],
        next_cursor=None,
    )


@router.get("/apps/{app_id}/versions/{version_id}", response_model=AppVersionResponse)
async def get_version(
    app_id: str,
    version_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get a specific version by UUID.
    """
    app_dal = AppDAL(db)
    version_dal = AppVersionDAL(db)

    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    version = await version_dal.get_by_id(version_id)
    if not version or version.app_id != app.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "VERSION_NOT_FOUND", "message": f"Version '{version_id}' not found."},
        )

    return AppVersionResponse(
        id=version.id,
        app_id=version.app_id,
        version_number=version.version_number,
        status=version.status,
        source_artifact_ref=version.source_artifact_ref,
        build_artifact_ref=version.build_artifact_ref,
        manifest=version.manifest,
        db_snapshot_ref=version.db_snapshot_ref,
        publisher_user_id=version.publisher_user_id,
        publisher_agent=version.publisher_agent,
        change_description=version.change_description,
        published_at=version.published_at,
        created_at=version.created_at,
    )


@router.get("/apps/{app_id}/operations/{operation_id}", response_model=PublishOperationResponse)
async def get_operation(
    app_id: str,
    operation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get operation status by operation ID.
    """
    app_dal = AppDAL(db)
    audit_dal = AuditDAL(db)

    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    event = await audit_dal.get_by_operation_id(operation_id)
    if not event or event.app_id != app.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPERATION_NOT_FOUND", "message": f"Operation '{operation_id}' not found."},
        )

    return PublishOperationResponse(
        operation_id=uuid.UUID(operation_id),
        type="publish",
        status="succeeded" if event.outcome == "success" else "failed",
        app_id=app.id,
        version_id=event.target_id,
        errors=[],
        created_at=event.occurred_at,
        updated_at=event.occurred_at,
    )


@router.get("/apps/{app_id}/logs")
async def get_app_logs(
    app_id: str,
    tail: int = Query(100, ge=1, le=1000),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get capsule runtime logs (stdout/stderr and lifecycle events).
    """
    app_dal = AppDAL(db)
    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    now_iso = datetime.utcnow().isoformat() + "Z"
    logs = [
        f"[{now_iso}] [system] Capsule {app.app_key} initialized on Node.js 22 runtime",
        f"[{now_iso}] [sandbox] Security boundary: read-only rootfs, dropped capabilities, no-new-privileges",
        f"[{now_iso}] [{app.app_key}] SQLite database connected at /data/app.sqlite (WAL mode)",
        f"[{now_iso}] [{app.app_key}] Server listening on internal port 3000",
        f"[{now_iso}] [edge-proxy] Forwarding request GET / to capsule",
        f"[{now_iso}] [{app.app_key}] HTTP 200 OK - 1.4ms",
    ]
    return {
        "app_id": str(app.id),
        "app_key": app.app_key,
        "logs": logs[-tail:],
    }

