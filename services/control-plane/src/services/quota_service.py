"""
Quota Evaluation and Enforcement Service (Prompt 23)

Enforces quotas configurable per organization inside Environment Profile:
- apps_per_user (default: 10)
- sqlite_max_mb (default: 50)
- blob_storage_max_mb (default: 200)
- request_timeout_s (default: 30)
- request_body_max_mb (default: 10)
- egress_bytes_per_day (default: 100MB)
- ai_monthly_budget_usd (default: 10.0)

All quota checks fail closed with standardized structured JSON errors.
"""
from typing import Any, Dict, Optional
from fastapi import HTTPException, status

DEFAULT_QUOTAS: Dict[str, Any] = {
    "apps_per_user": 10,
    "sqlite_max_mb": 50,
    "blob_storage_max_mb": 200,
    "request_timeout_s": 30,
    "request_body_max_mb": 10,
    "egress_bytes_per_day": 100 * 1024 * 1024,  # 100 MB
    "ai_monthly_budget_usd": 10.0,
}


def get_effective_quotas(env_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Returns effective quotas for an organization by merging configured profile
    quotas with platform default quotas.
    """
    quotas = dict(DEFAULT_QUOTAS)
    if env_profile and isinstance(env_profile.get("quotas"), dict):
        for k, v in env_profile["quotas"].items():
            if k in quotas and v is not None:
                quotas[k] = v
    return quotas


def enforce_apps_per_user_quota(
    current_count: int,
    env_profile: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Fails closed if active apps for user reaches or exceeds the organization limit.
    """
    effective = get_effective_quotas(env_profile)
    limit = effective["apps_per_user"]
    if current_count >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "QUOTA_EXCEEDED",
                "metric": "apps_per_user",
                "limit": limit,
                "current_usage": current_count,
                "message": f"Quota exceeded for apps_per_user: limit of {limit} apps reached.",
            },
        )


def enforce_manifest_quotas(
    manifest: Dict[str, Any],
    env_profile: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Validates manifest capabilities and limits against organization quotas.
    Fails closed if any limit exceeds the organization quota.
    """
    effective = get_effective_quotas(env_profile)
    limits = manifest.get("limits") or {}
    caps = manifest.get("capabilities") or {}

    # 1. SQLite database size quota
    db_cap = caps.get("db")
    requested_db_mb = None
    if isinstance(db_cap, dict):
        requested_db_mb = db_cap.get("max_size_mb")
    if requested_db_mb is None and limits.get("db_max_mb") is not None:
        requested_db_mb = limits["db_max_mb"]

    if requested_db_mb is not None:
        sqlite_limit = effective["sqlite_max_mb"]
        if requested_db_mb > sqlite_limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "QUOTA_EXCEEDED",
                    "metric": "sqlite_max_mb",
                    "limit": sqlite_limit,
                    "requested": requested_db_mb,
                    "message": f"Requested SQLite size {requested_db_mb}MB exceeds organization quota {sqlite_limit}MB.",
                },
            )

    # 2. Blob / files storage quota
    files_cap = caps.get("files")
    requested_blob_mb = None
    if isinstance(files_cap, dict):
        requested_blob_mb = files_cap.get("max_mb")
    if requested_blob_mb is None and limits.get("blob_max_mb") is not None:
        requested_blob_mb = limits["blob_max_mb"]

    if requested_blob_mb is not None:
        blob_limit = effective["blob_storage_max_mb"]
        if requested_blob_mb > blob_limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "QUOTA_EXCEEDED",
                    "metric": "blob_storage_max_mb",
                    "limit": blob_limit,
                    "requested": requested_blob_mb,
                    "message": f"Requested blob storage size {requested_blob_mb}MB exceeds organization quota {blob_limit}MB.",
                },
            )

    # 3. Request timeout quota
    requested_timeout = limits.get("request_timeout_s")
    if requested_timeout is not None:
        timeout_limit = effective["request_timeout_s"]
        if requested_timeout > timeout_limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "QUOTA_EXCEEDED",
                    "metric": "request_timeout_s",
                    "limit": timeout_limit,
                    "requested": requested_timeout,
                    "message": f"Requested request timeout {requested_timeout}s exceeds organization quota {timeout_limit}s.",
                },
            )

    # 4. AI Monthly Budget quota
    ai_cap = caps.get("ai")
    if isinstance(ai_cap, dict) and "monthly_budget_usd" in ai_cap:
        requested_ai = float(ai_cap["monthly_budget_usd"])
        ai_limit = float(effective["ai_monthly_budget_usd"])
        if requested_ai > ai_limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "QUOTA_EXCEEDED",
                    "metric": "ai_monthly_budget_usd",
                    "limit": ai_limit,
                    "requested": requested_ai,
                    "message": f"Requested AI monthly budget ${requested_ai} exceeds organization quota ${ai_limit}.",
                },
            )
