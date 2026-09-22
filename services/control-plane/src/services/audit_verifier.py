"""
Audit Verifier and Cryptographic Hash Chain Module
Provides tamper-evidence verification, SHA-256 chain calculation,
and strict multi-layer redaction of sensitive credentials.
"""
import re
import json
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

GENESIS_HASH = "0" * 64

# Sensitive key patterns to redact
SENSITIVE_KEY_PATTERNS = [
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"key", re.IGNORECASE),
    re.compile(r"session", re.IGNORECASE),
    re.compile(r"ticket", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"jwt", re.IGNORECASE),
    re.compile(r"cookie", re.IGNORECASE),
    re.compile(r"bearer", re.IGNORECASE),
    re.compile(r"private", re.IGNORECASE),
]

# Whitelist of keys ending or containing 'key' that are NOT sensitive
SAFE_KEYS = {
    "app_key",
    "capability_key",
    "key_id",
    "idempotency_key",
    "event_key",
    "routing_key",
    "sort_key",
    "public_key",
}

# Regex to detect tokens/secrets in string values
VALUE_SECRET_PATTERNS = [
    re.compile(r"^Bearer\s+[A-Za-z0-9\-_\.]+", re.IGNORECASE),
    re.compile(r"^[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_.+/=]{20,}$"),  # JWT
    re.compile(r"^(?:sk|ghp|gho|glpat|slack|cap|sess)_[A-Za-z0-9\-_]{16,}"),  # Common secret token prefixes
    re.compile(r"^sess_[a-f0-9\-]{16,}", re.IGNORECASE),  # Session IDs
]


def is_sensitive_key(key: str) -> bool:
    clean = key.strip().lower()
    if clean in SAFE_KEYS:
        return False
    return any(p.search(clean) for p in SENSITIVE_KEY_PATTERNS)


def is_sensitive_value(val: str) -> bool:
    if not isinstance(val, str) or len(val) < 16:
        return False
    return any(p.search(val) for p in VALUE_SECRET_PATTERNS)


def redact_audit_metadata(data: Any) -> Any:
    """
    Recursively scans and replaces sensitive keys and secret-like values
    with '[REDACTED]'.
    """
    if isinstance(data, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in data.items():
            if is_sensitive_key(str(k)):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_audit_metadata(v)
        return cleaned
    elif isinstance(data, list):
        return [redact_audit_metadata(item) for item in data]
    elif isinstance(data, str):
        if is_sensitive_value(data):
            return "[REDACTED]"
        return data
    return data


def format_audit_timestamp(dt: Union[datetime, str]) -> str:
    """
    Converts datetime or ISO string to canonical ISO-8601 UTC string.
    """
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)


def compute_audit_event_hash(
    *,
    organization_id: Optional[Union[str, Any]],
    sequence_number: int,
    prev_hash: str,
    action: str,
    outcome: str = "success",
    app_id: Optional[Union[str, Any]] = None,
    actor_user_id: Optional[Union[str, Any]] = None,
    actor_agent: Optional[str] = None,
    actor_tool: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[Union[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    occurred_at: Union[datetime, str],
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Computes a cryptographic SHA-256 hash for an audit event row.
    Deterministic JSON serialization ensures exact hash matching across verification.
    """
    clean_meta = redact_audit_metadata(metadata or {})
    payload = {
        "organization_id": str(organization_id) if organization_id else None,
        "sequence_number": int(sequence_number),
        "prev_hash": str(prev_hash or GENESIS_HASH),
        "action": str(action),
        "outcome": str(outcome),
        "app_id": str(app_id) if app_id else None,
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "actor_agent": str(actor_agent) if actor_agent else None,
        "actor_tool": str(actor_tool) if actor_tool else None,
        "target_type": str(target_type) if target_type else None,
        "target_id": str(target_id) if target_id else None,
        "ip_address": str(ip_address) if ip_address else None,
        "user_agent": str(user_agent) if user_agent else None,
        "occurred_at": format_audit_timestamp(occurred_at),
        "metadata": clean_meta,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
