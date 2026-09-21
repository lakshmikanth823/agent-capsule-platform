"""
Pydantic schemas matching docs/api-cli-spec/openapi.yaml.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


class ArtifactRef(BaseModel):
    ref: str
    sha256: Optional[str] = None


class CreateAppRequest(BaseModel):
    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$", description="App key / identifier")
    name: str = Field(..., max_length=80)
    description: Optional[str] = None
    shape: Literal["web-app"] = "web-app"
    runtime: Literal["node22"] = "node22"
    manifest: Dict[str, Any]


class PublishRequest(BaseModel):
    manifest: Dict[str, Any]
    artifact: Optional[ArtifactRef] = None
    change_description: Optional[str] = Field(None, max_length=2000)
    expected_current_version: Optional[int] = Field(None, ge=1)


class ValidateRequest(BaseModel):
    manifest: Dict[str, Any]


class AppResponse(BaseModel):
    id: uuid.UUID
    organization_id: Optional[uuid.UUID] = None
    owner_user_id: Optional[uuid.UUID] = None
    app_key: str
    name: str
    description: Optional[str] = None
    status: str
    shape: str
    runtime: str
    current_version_id: Optional[uuid.UUID] = None
    app_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AppListResponse(BaseModel):
    items: List[AppResponse]
    next_cursor: Optional[str] = None


class AppVersionResponse(BaseModel):
    id: uuid.UUID
    app_id: uuid.UUID
    version_number: int
    status: str
    source_artifact_ref: str
    build_artifact_ref: Optional[str] = None
    manifest: Dict[str, Any]
    db_snapshot_ref: str
    publisher_user_id: Optional[uuid.UUID] = None
    publisher_agent: Optional[str] = None
    publisher_name: Optional[str] = None
    change_description: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VersionListResponse(BaseModel):
    items: List[AppVersionResponse]
    next_cursor: Optional[str] = None


class PublishOperationResponse(BaseModel):
    operation_id: uuid.UUID
    type: Literal["publish", "rollback"] = "publish"
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "pending_approval"]
    app_id: uuid.UUID
    version_id: Optional[uuid.UUID] = None
    errors: List[Any] = []
    created_at: datetime
    updated_at: datetime


class RollbackRequest(BaseModel):
    target_version_id: Optional[uuid.UUID] = None
    target_version_number: Optional[int] = None
    mode: Literal["code_only", "code_and_data"] = "code_only"
    confirm_data_restore: bool = False
    reason: Optional[str] = None


class DataLossWarning(BaseModel):
    target_version: int
    snapshot_ref: str
    snapshot_time: Optional[datetime] = None
    time_window_seconds: int
    current_records: int
    target_records: int
    estimated_records_lost: int
    recovery_snapshot_available: bool = True
    message: str


class RollbackOperationResponse(BaseModel):
    operation_id: uuid.UUID
    type: Literal["rollback"] = "rollback"
    status: Literal["succeeded", "failed"] = "succeeded"
    app_id: uuid.UUID
    version_id: uuid.UUID
    version_number: int
    target_version_number: int
    mode: Literal["code_only", "code_and_data"]
    recovery_snapshot_ref: str
    data_restored: bool
    data_loss_warning: Optional[DataLossWarning] = None
    created_at: datetime


class ValidationCheckResponse(BaseModel):
    name: str
    status: Literal["pass", "fail", "warn"]
    code: Optional[str] = None
    message: Optional[str] = None
    path: Optional[str] = None
    hint: Optional[str] = None


class ValidationResultResponse(BaseModel):
    valid: bool
    checks: List[ValidationCheckResponse]
    required_approvals: List[str] = []
    warnings: List[str] = []


class CreatePublishTokenRequest(BaseModel):
    app_id: Optional[uuid.UUID] = None
    expires_in_seconds: int = Field(3600, ge=60, le=86400)


class PublishTokenResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    expires_in: int
    scope: str
    app_id: Optional[str] = None


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class CapabilityApprovalResponse(BaseModel):
    id: uuid.UUID
    app_id: uuid.UUID
    requested_version_id: Optional[uuid.UUID] = None
    capability_key: str
    previous_value: Optional[Any] = None
    requested_value: Optional[Any] = None
    status: str
    requested_by_user_id: Optional[uuid.UUID] = None
    approved_by_user_id: Optional[uuid.UUID] = None
    requested_at: datetime
    decided_at: Optional[datetime] = None


class ApprovalsListResponse(BaseModel):
    approvals: List[CapabilityApprovalResponse]
    pending_count: int


class ApprovalDecisionResponse(BaseModel):
    approval_id: uuid.UUID
    status: str
    version_id: Optional[uuid.UUID] = None
    version_status: Optional[str] = None
    version_number: Optional[int] = None

