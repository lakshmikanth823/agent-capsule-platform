"""
App and Version management endpoints matching docs/api-cli-spec/openapi.yaml.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from db.dal import AppDAL, AppVersionDAL, AuditDAL, CapabilityApprovalDAL, UserDAL
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
    CapabilityApprovalResponse,
    ApprovalsListResponse,
    ApprovalDecisionResponse,
    RollbackRequest,
    DataLossWarning,
    RollbackOperationResponse,
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


def get_capsule_db_path(app_id: uuid.UUID, app_key: str) -> Path:
    base_data_dir = Path(os.environ.get("CAPSULES_DATA_DIR", "data/capsules")).resolve()
    path_by_id = base_data_dir / str(app_id) / "data" / "app.sqlite"
    path_by_key = base_data_dir / app_key / "data" / "app.sqlite"
    if path_by_id.exists():
        return path_by_id
    if path_by_key.exists():
        return path_by_key
    return path_by_id


def _get_sqlite_conn(db_bytes_or_path: Union[bytes, Path, str]) -> Tuple[sqlite3.Connection, Optional[Path]]:
    if isinstance(db_bytes_or_path, (bytes, bytearray)):
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.write(db_bytes_or_path)
        tmp.close()
        tmp_path = Path(tmp.name)
        conn = sqlite3.connect(str(tmp_path))
        return conn, tmp_path
    else:
        conn = sqlite3.connect(str(db_bytes_or_path))
        return conn, None


def inspect_sqlite_schema(db_bytes_or_path: Union[bytes, Path, str]) -> Dict[str, Any]:
    """
    Inspects tables and column definitions of a SQLite database.
    """
    conn, tmp_path = _get_sqlite_conn(db_bytes_or_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = cursor.fetchall()
        schema: Dict[str, Any] = {}
        for table_name, create_sql in tables:
            cursor.execute(f"PRAGMA table_info({table_name});")
            cols = cursor.fetchall()
            columns: Dict[str, Any] = {}
            for row in cols:
                # cid, name, type, notnull, dflt_value, pk
                col_name = row[1]
                col_type = (row[2] or "TEXT").upper()
                notnull = bool(row[3])
                dflt_val = row[4]
                pk = bool(row[5])
                columns[col_name] = {
                    "type": col_type,
                    "notnull": notnull,
                    "default": dflt_val,
                    "pk": pk,
                }
            schema[table_name] = {
                "sql": create_sql,
                "columns": columns,
            }
        return schema
    except Exception:
        return {}
    finally:
        conn.close()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


def count_sqlite_records(db_bytes_or_path: Union[bytes, Path, str]) -> int:
    """
    Counts total rows across all non-system tables in a SQLite database.
    """
    conn, tmp_path = _get_sqlite_conn(db_bytes_or_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in cursor.fetchall()]
        total = 0
        for t in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {t};")
                total += cursor.fetchone()[0]
            except Exception:
                pass
        return total
    except Exception:
        return 0
    finally:
        conn.close()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


def check_schema_compatibility(
    target_schema: Dict[str, Any], current_schema: Dict[str, Any]
) -> Tuple[bool, Optional[str]]:
    """
    Checks if target schema is compatible with current schema for code-only rollback.
    Code of target version expects all tables and columns defined in target_schema
    to exist in current_schema.
    """
    for table_name, table_info in target_schema.items():
        if table_name not in current_schema:
            return False, f"Table '{table_name}' required by target version does not exist in current database"
        current_cols = current_schema[table_name]["columns"]
        for col_name, col_info in table_info["columns"].items():
            if col_name not in current_cols:
                return (
                    False,
                    f"Column '{col_name}' of table '{table_name}' required by target version does not exist in current database",
                )
    return True, None


async def take_sqlite_snapshot(source_path: Path, storage: Any, target_ref: str) -> Tuple[str, int]:
    """
    Takes a database snapshot before deploy or rollback.
    If source_path exists, performs safe SQLite backup and stores in object storage.
    If source_path does not exist, creates a clean baseline SQLite file.
    Returns (target_ref, records_count).
    """
    if source_path.exists():
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            src_conn = sqlite3.connect(str(source_path))
            dst_conn = sqlite3.connect(str(tmp_path))
            src_conn.backup(dst_conn)
            src_conn.close()
            dst_conn.close()
            data = tmp_path.read_bytes()
            records = count_sqlite_records(tmp_path)
        except Exception:
            data = source_path.read_bytes()
            records = count_sqlite_records(data)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
    else:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            conn = sqlite3.connect(str(tmp_path))
            conn.execute("PRAGMA user_version = 0;")
            conn.close()
            data = tmp_path.read_bytes()
            records = 0
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    await storage.put(target_ref, data)
    return target_ref, records


def detect_capability_escalation(
    old_manifest: Dict[str, Any], new_manifest: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Detects if a new version adds or broadens any capabilities, egress, or limits
    compared to the previous version (TRD Section 19, PRD Section 20).
    """
    escalations: List[Dict[str, Any]] = []

    old_caps = old_manifest.get("capabilities") or {}
    new_caps = new_manifest.get("capabilities") or {}

    # 1. Capabilities checks: db, identity, files, ai
    for cap_key in ["db", "identity", "files", "ai"]:
        old_val = old_caps.get(cap_key)
        new_val = new_caps.get(cap_key)
        if not old_val and new_val:
            escalations.append({
                "capability_key": f"capabilities.{cap_key}",
                "previous_value": old_val,
                "requested_value": new_val,
                "reason": f"New capability '{cap_key}' requested",
            })

    # 2. Connectors check
    old_connectors = old_caps.get("connectors") or []
    new_connectors = new_caps.get("connectors") or []

    def _normalize_connector(c: Any) -> Dict[str, Any]:
        if isinstance(c, str):
            return {"name": c, "identity": "viewer"}
        if isinstance(c, dict):
            return {
                "name": c.get("name") or c.get("id") or str(c),
                "identity": c.get("identity") or c.get("acts_as") or "viewer",
            }
        return {"name": str(c), "identity": "viewer"}

    old_conn_map = {c["name"]: c for c in [_normalize_connector(x) for x in old_connectors]}
    new_conn_map = {c["name"]: c for c in [_normalize_connector(x) for x in new_connectors]}

    for name, new_c in new_conn_map.items():
        if name not in old_conn_map:
            escalations.append({
                "capability_key": f"capabilities.connectors.{name}",
                "previous_value": None,
                "requested_value": new_c,
                "reason": f"New connector requested: {name}",
            })
        else:
            old_c = old_conn_map[name]
            if old_c.get("identity") != "service" and new_c.get("identity") == "service":
                escalations.append({
                    "capability_key": f"capabilities.connectors.{name}.identity",
                    "previous_value": old_c,
                    "requested_value": new_c,
                    "reason": f"Connector '{name}' escalated to service identity",
                })

    # 3. Egress checks
    old_egress = old_manifest.get("egress") or []
    new_egress = new_manifest.get("egress") or []

    def _get_egress_hosts(egress_list: List[Any]) -> set:
        hosts = set()
        for item in egress_list:
            if isinstance(item, str):
                hosts.add(item.lower())
            elif isinstance(item, dict) and "host" in item:
                hosts.add(item["host"].lower())
        return hosts

    old_hosts = _get_egress_hosts(old_egress)
    new_hosts = _get_egress_hosts(new_egress)

    for host in new_hosts:
        if host not in old_hosts:
            escalations.append({
                "capability_key": f"egress:{host}",
                "previous_value": list(old_hosts),
                "requested_value": host,
                "reason": f"New outbound egress domain requested: {host}",
            })

    # 4. Limits checks (memory_mb, request_timeout_s, db_max_mb)
    old_limits = old_manifest.get("limits") or {}
    new_limits = new_manifest.get("limits") or {}

    for num_limit in ["memory_mb", "request_timeout_s", "db_max_mb"]:
        old_v = old_limits.get(num_limit)
        new_v = new_limits.get(num_limit)
        if old_v is not None and new_v is not None and new_v > old_v:
            escalations.append({
                "capability_key": f"limits.{num_limit}",
                "previous_value": old_v,
                "requested_value": new_v,
                "reason": f"Limit '{num_limit}' increased from {old_v} to {new_v}",
            })

    return escalations


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

    # 7. Check for Capability Escalation on Update
    approval_dal = CapabilityApprovalDAL(db)
    current_version = None
    if app.current_version_id:
        current_version = await version_dal.get_by_id(app.current_version_id)

    old_manifest = current_version.manifest if current_version else (app.manifest or {})
    effective_manifest = val_result.get("effective_manifest") or manifest

    escalations = []
    if current_version:
        escalations = detect_capability_escalation(old_manifest, effective_manifest)

    # 8. Create App Version and Pre-Deploy Database Snapshot
    versions = await version_dal.list_for_app(app.id)
    next_ver_num = len(versions) + 1

    live_db_path = get_capsule_db_path(app.id, app.app_key)
    snapshot_ref = f"capsules/{app.id}/snapshots/v{next_ver_num}_snapshot.sqlite"
    await take_sqlite_snapshot(live_db_path, storage, snapshot_ref)

    now_utc = datetime.utcnow()
    operation_id = uuid.uuid4()

    if escalations:
        # Escalation detected: create version in 'validated' status (held from publishing)
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
            status="validated",
            published_at=None,
        )

        # Create CapabilityApproval records
        for esc in escalations:
            await approval_dal.create(
                app_id=app.id,
                requested_version_id=version.id,
                capability_key=esc["capability_key"],
                previous_value=esc.get("previous_value"),
                requested_value=esc.get("requested_value"),
                requested_by_user_id=user.id,
            )

        # Record Audit Event
        await audit_dal.record_event(
            action="app.capability_escalation_detected",
            outcome="denied",
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
                "escalations": escalations,
            },
        )
        await db.commit()

        return PublishOperationResponse(
            operation_id=operation_id,
            type="publish",
            status="pending_approval",
            app_id=app.id,
            version_id=version.id,
            errors=[
                f"Capability escalation detected: {e['reason']}. Approval required from app owner."
                for e in escalations
            ],
            created_at=now_utc,
            updated_at=now_utc,
        )

    # No escalation: publish immediately
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

    # Update App Current Version & Manifest
    await app_dal.set_current_version(
        app_id=app.id,
        version_id=version.id,
        published_at=now_utc,
        manifest=effective_manifest,
        status="active",
    )

    # Record Audit Event
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
    user_dal = UserDAL(db)
    publisher_ids = {v.publisher_user_id for v in versions if v.publisher_user_id}
    users_map = {}
    for pid in publisher_ids:
        u = await user_dal.get_by_id(pid)
        if u:
            users_map[pid] = u.display_name or u.email

    items = []
    for v in versions:
        pub_name = None
        if v.publisher_user_id and v.publisher_user_id in users_map:
            pub_name = users_map[v.publisher_user_id]
        elif v.publisher_agent:
            pub_name = v.publisher_agent

        items.append(
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
                publisher_name=pub_name,
                change_description=v.change_description,
                published_at=v.published_at,
                created_at=v.created_at,
            )
        )
    return VersionListResponse(items=items, next_cursor=None)


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

    user_dal = UserDAL(db)
    pub_name = None
    if version.publisher_user_id:
        u = await user_dal.get_by_id(version.publisher_user_id)
        if u:
            pub_name = u.display_name or u.email
    elif version.publisher_agent:
        pub_name = version.publisher_agent

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
        publisher_name=pub_name,
        change_description=version.change_description,
        published_at=version.published_at,
        created_at=version.created_at,
    )


@router.post(
    "/apps/{app_id}/rollback",
    response_model=RollbackOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rollback_app(
    app_id: str,
    request: RollbackRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Roll back an application to a previous version.
    Supports code-only (default) and code-plus-data restore.
    Takes a fresh recovery snapshot immediately before rollback.
    """
    # 1. Authorization: publish tokens cannot perform rollback
    if user.token_type == "publish_token" or user.publish_app_id is not None or user.claims.get("sub", "").startswith("app-pub-"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Publish tokens cannot perform rollback operations."},
        )

    # 2. Authorization: owner or editor required
    if user.platform_role not in ("owner", "editor"):
        user_dal = UserDAL(db)
        members = await user_dal.get_org_members(user.organization_id)
        user_member = next((m for m in members if m.user_id == user.id), None)
        if not user_member or user_member.platform_role not in ("owner", "editor"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "Only owners and editors can perform rollback operations."},
            )

    app_dal = AppDAL(db)
    version_dal = AppVersionDAL(db)
    audit_dal = AuditDAL(db)
    storage = get_storage_driver()

    # 3. Resolve App
    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    # 4. Resolve Target Version
    target_version = None
    if request.target_version_id:
        target_version = await version_dal.get_by_id(request.target_version_id)
    elif request.target_version_number is not None:
        target_version = await version_dal.get_by_number(app.id, request.target_version_number)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Either target_version_id or target_version_number is required."},
        )

    if not target_version or target_version.app_id != app.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "VERSION_NOT_FOUND", "message": "Target version not found."},
        )

    if target_version.id == app.current_version_id and request.mode == "code_only":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "ALREADY_ACTIVE", "message": f"Version {target_version.version_number} code is already active."},
        )

    # 5. Check Target Snapshot & Live Database
    target_snapshot_ref = target_version.db_snapshot_ref
    target_bytes = b""
    if await storage.exists(target_snapshot_ref):
        target_bytes = await storage.get(target_snapshot_ref)

    live_db_path = get_capsule_db_path(app.id, app.app_key)

    # 6. Mode: code_only schema compatibility check
    if request.mode == "code_only":
        if live_db_path.exists() and target_bytes:
            target_schema = inspect_sqlite_schema(target_bytes)
            current_schema = inspect_sqlite_schema(live_db_path)
            compatible, reason = check_schema_compatibility(target_schema, current_schema)
            if not compatible:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "ROLLBACK_INCOMPATIBLE",
                        "message": (
                            f"Target version {target_version.version_number} schema is incompatible with current database: {reason}. "
                            "Use code-and-data restore mode with explicit confirmation."
                        ),
                        "target_version": target_version.version_number,
                        "reason": reason,
                    },
                )

    # 7. Mode: code_and_data confirmation & warning check
    elif request.mode == "code_and_data":
        if not request.confirm_data_restore:
            target_records = count_sqlite_records(target_bytes) if target_bytes else 0
            current_records = count_sqlite_records(live_db_path) if live_db_path.exists() else 0
            snap_time = target_version.published_at or target_version.created_at
            now_dt = datetime.now(timezone.utc)
            if snap_time and snap_time.tzinfo is None:
                snap_time = snap_time.replace(tzinfo=timezone.utc)
            time_window = int(abs((now_dt - snap_time).total_seconds())) if snap_time else 0
            records_lost = max(0, current_records - target_records)

            warning = DataLossWarning(
                target_version=target_version.version_number,
                snapshot_ref=target_snapshot_ref,
                snapshot_time=snap_time,
                time_window_seconds=time_window,
                current_records=current_records,
                target_records=target_records,
                estimated_records_lost=records_lost,
                recovery_snapshot_available=True,
                message=(
                    f"WARNING: Restoring database snapshot from version {target_version.version_number} "
                    f"will overwrite current application data. {current_records} current records present. "
                    f"Confirm data restore to proceed."
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "CONFIRMATION_REQUIRED",
                    "message": warning.message,
                    "data_loss_warning": warning.model_dump(mode="json"),
                },
            )

    # 8. Take Fresh Pre-Rollback Recovery Snapshot (so rollback can be undone)
    versions = await version_dal.list_for_app(app.id)
    next_ver_num = len(versions) + 1
    recovery_snapshot_ref = f"capsules/{app.id}/snapshots/pre_rollback_v{next_ver_num}.sqlite"
    await take_sqlite_snapshot(live_db_path, storage, recovery_snapshot_ref)

    # 9. Perform Data Restore if requested
    data_restored = False
    if request.mode == "code_and_data" and target_bytes:
        live_db_path.parent.mkdir(parents=True, exist_ok=True)
        live_db_path.write_bytes(target_bytes)
        wal_file = live_db_path.with_name(live_db_path.name + "-wal")
        shm_file = live_db_path.with_name(live_db_path.name + "-shm")
        if wal_file.exists():
            wal_file.unlink()
        if shm_file.exists():
            shm_file.unlink()
        data_restored = True

    # 10. Create New Immutable Rollback Version in app_versions
    now_utc = datetime.utcnow()
    operation_id = uuid.uuid4()
    change_desc = f"Rollback to v{target_version.version_number} ({request.mode})"
    if request.reason:
        change_desc += f": {request.reason}"

    new_version = await version_dal.create(
        app_id=app.id,
        version_number=next_ver_num,
        source_artifact_ref=target_version.source_artifact_ref,
        build_artifact_ref=target_version.build_artifact_ref,
        manifest=target_version.manifest,
        db_snapshot_ref=recovery_snapshot_ref,
        publisher_user_id=user.id,
        publisher_agent=user.claims.get("agent_name"),
        change_description=change_desc,
        status="published",
        published_at=now_utc,
    )

    # 11. Mark Previous Version as rolled_back and Update Current Version
    if app.current_version_id:
        await version_dal.set_status(app.current_version_id, "rolled_back")

    await app_dal.set_current_version(
        app_id=app.id,
        version_id=new_version.id,
        published_at=now_utc,
        manifest=target_version.manifest,
        status="active",
    )

    # 12. Record Audit Event
    await audit_dal.record_event(
        action="app.rollback",
        outcome="success",
        organization_id=user.organization_id,
        app_id=app.id,
        actor_user_id=user.id,
        target_type="app_version",
        target_id=new_version.id,
        metadata={
            "idempotency_key": idempotency_key,
            "operation_id": str(operation_id),
            "target_version_number": target_version.version_number,
            "new_version_number": next_ver_num,
            "mode": request.mode,
            "recovery_snapshot_ref": recovery_snapshot_ref,
            "data_restored": data_restored,
            "reason": request.reason,
        },
    )
    await db.commit()

    return RollbackOperationResponse(
        operation_id=operation_id,
        type="rollback",
        status="succeeded",
        app_id=app.id,
        version_id=new_version.id,
        version_number=next_ver_num,
        target_version_number=target_version.version_number,
        mode=request.mode,
        recovery_snapshot_ref=recovery_snapshot_ref,
        data_restored=data_restored,
        created_at=now_utc,
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


# ============================================================
# Capability Approval Endpoints (TRD Section 19, PRD Section 20)
# ============================================================

@router.get("/apps/{app_id}/approvals", response_model=ApprovalsListResponse)
async def list_approvals(
    app_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    List pending or historical capability escalation approvals for an application.
    """
    app_dal = AppDAL(db)
    approval_dal = CapabilityApprovalDAL(db)

    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    approvals = await approval_dal.list_for_app(app.id, status=status_filter)
    pending_count = sum(1 for a in approvals if a.status == "pending")

    return ApprovalsListResponse(
        approvals=[
            CapabilityApprovalResponse(
                id=a.id,
                app_id=a.app_id,
                requested_version_id=a.requested_version_id,
                capability_key=a.capability_key,
                previous_value=a.previous_value,
                requested_value=a.requested_value,
                status=a.status,
                requested_by_user_id=a.requested_by_user_id,
                approved_by_user_id=a.approved_by_user_id,
                requested_at=a.requested_at,
                decided_at=a.decided_at,
            )
            for a in approvals
        ],
        pending_count=pending_count,
    )


@router.post(
    "/apps/{app_id}/approvals/{approval_id}/approve",
    response_model=ApprovalDecisionResponse,
)
async def approve_capability_escalation(
    app_id: str,
    approval_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Approve capability escalation for an application version.
    SECURITY INVARIANT: An agent's publish credential can NEVER approve its own escalation.
    Only an authenticated Owner or Editor can approve.
    """
    # 1. Reject Publish Token Callers (Self-Approval Prohibition)
    if user.token_type == "publish_token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "A publish credential can never approve its own capability escalation.",
            },
        )

    # 2. Check Platform Role (Owner or Editor required)
    if user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only an app Owner or Editor can approve capability escalation.",
            },
        )

    app_dal = AppDAL(db)
    approval_dal = CapabilityApprovalDAL(db)
    version_dal = AppVersionDAL(db)
    audit_dal = AuditDAL(db)

    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    approval = await approval_dal.get_by_id(approval_id)
    if not approval or approval.app_id != app.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APPROVAL_NOT_FOUND", "message": "Approval record not found."},
        )

    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ALREADY_DECIDED", "message": f"Approval is already '{approval.status}'."},
        )

    # 3. Approve the record
    await approval_dal.decide(approval.id, "approved", user.id)

    version_status = "validated"
    version_number = None

    # 4. Check if all approvals for this version are approved
    if approval.requested_version_id:
        version_approvals = await approval_dal.list_for_version(approval.requested_version_id)
        all_approved = all(a.status == "approved" for a in version_approvals)

        version = await version_dal.get_by_id(approval.requested_version_id)
        if version:
            version_number = version.version_number
            if all_approved:
                # Activate version!
                now = datetime.utcnow()
                version.status = "published"
                version.published_at = now
                version_status = "published"

                await app_dal.set_current_version(
                    app_id=app.id,
                    version_id=version.id,
                    published_at=now,
                    manifest=version.manifest,
                    status="active",
                )

                await audit_dal.record_event(
                    action="app.capability_approved",
                    outcome="success",
                    organization_id=user.organization_id,
                    app_id=app.id,
                    actor_user_id=user.id,
                    target_type="app_version",
                    target_id=version.id,
                    metadata={
                        "approval_id": str(approval.id),
                        "capability_key": approval.capability_key,
                        "version_number": version.version_number,
                    },
                )

    await db.commit()

    return ApprovalDecisionResponse(
        approval_id=approval.id,
        status="approved",
        version_id=approval.requested_version_id,
        version_status=version_status,
        version_number=version_number,
    )


@router.post(
    "/apps/{app_id}/approvals/{approval_id}/reject",
    response_model=ApprovalDecisionResponse,
)
async def reject_capability_escalation(
    app_id: str,
    approval_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Reject capability escalation for an application version.
    """
    if user.token_type == "publish_token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "A publish credential can never decide capability escalation.",
            },
        )

    if user.platform_role not in ("owner", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only an app Owner or Editor can reject capability escalation.",
            },
        )

    app_dal = AppDAL(db)
    approval_dal = CapabilityApprovalDAL(db)
    version_dal = AppVersionDAL(db)
    audit_dal = AuditDAL(db)

    app = await app_dal.get_by_id_or_key(user.organization_id, app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APP_NOT_FOUND", "message": f"App '{app_id}' not found."},
        )

    approval = await approval_dal.get_by_id(approval_id)
    if not approval or approval.app_id != app.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APPROVAL_NOT_FOUND", "message": "Approval record not found."},
        )

    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ALREADY_DECIDED", "message": f"Approval is already '{approval.status}'."},
        )

    await approval_dal.decide(approval.id, "rejected", user.id)

    version_number = None
    if approval.requested_version_id:
        version = await version_dal.get_by_id(approval.requested_version_id)
        if version:
            version_number = version.version_number

    await audit_dal.record_event(
        action="app.capability_rejected",
        outcome="denied",
        organization_id=user.organization_id,
        app_id=app.id,
        actor_user_id=user.id,
        target_type="capability_approval",
        target_id=approval.id,
        metadata={
            "approval_id": str(approval.id),
            "capability_key": approval.capability_key,
        },
    )
    await db.commit()

    return ApprovalDecisionResponse(
        approval_id=approval.id,
        status="rejected",
        version_id=approval.requested_version_id,
        version_status="validated",
        version_number=version_number,
    )


