"""
Policy Engine & Environment Profile Enforcement (Prompt 17)

Fulfills PRD FR-027, FR-028, FR-032:
- Versioned Environment Profile schema (capsule/v1alpha1)
- Policy ceiling computation (manifest may narrow, never widen)
- Structured policy validation errors
- Conditional capability approval (FR-032)
- App re-evaluation and grace period enforcement
"""
import copy
import fnmatch
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, Set

DEFAULT_ENVIRONMENT_PROFILE: Dict[str, Any] = {
    "version": "capsule/v1alpha1",
    "allowed_shapes": ["web-app"],
    "allowed_runtimes": ["node22"],
    "capabilities": {
        "allowed_capabilities": ["db", "files", "identity", "connectors", "ai"],
        "connectors": {
            "allowed_connectors": ["*"],
            "disabled_connectors": [],
            "allow_service_identity": True,
            "connector_identity_rules": {
                "slack.post": {"allowed_identities": ["viewer", "service"]},
                "sheets.read": {"allowed_identities": ["viewer"]},
                "google_sheets.read": {"allowed_identities": ["viewer"]},
                "fake.echo": {"allowed_identities": ["viewer", "service"]},
            },
        },
    },
    "egress": {
        "allowed_domains": ["*"],
        "denied_domains": ["169.254.169.254", "*.internal", "*.local", "*.corp"],
        "max_egress_bytes_per_day": 104857600,  # 100 MB
    },
    "sharing": {
        "default_scope": "org",
        "allow_external_sharing": False,
        "allow_guest_users": False,
        "max_audience_size": 100,
    },
    "ai": {
        "allowed_models": [
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "claude-3-5-sonnet",
            "gpt-4o-mini",
            "fake-llm",
        ],
        "max_monthly_budget_usd": 50.0,
        "rate_limits": {
            "requests_per_minute": 60,
            "requests_per_day": 1000,
        },
        "content_logging_enabled": False,
        "content_retention_days": 30,
        "enable_redaction": True,
    },
    "quotas": {
        "max_memory_mb": 512,
        "max_request_timeout_s": 60,
        "max_db_size_mb": 100,
        "max_blob_storage_mb": 500,
        "apps_per_user": 200,
        "request_body_max_mb": 10,
    },
    "approvals": {
        "audience_size_threshold": 10,
        "require_approval_for_service_identity": True,
        "sensitive_capabilities": ["connectors", "ai"],
        "require_approval_for_new_egress": True,
        "require_approval_for_org_wide_sharing": False,
    },
    "expiry": {
        "default_share_ttl_days": 90,
        "inactivity_warning_days": 60,
        "inactivity_suspend_days": 90,
    },
    "security": {
        "enforce_default_deny_egress": True,
        "allow_custom_env_vars": False,
        "prohibit_raw_sockets": True,
        "require_signed_identity_header": True,
    },
    "compliance": {
        "grace_period_hours": 72,
        "enforcement_action": "restrict",
    },
    "governance": {
        "owner_left_policy": "grace_period",
        "owner_left_grace_period_days": 14,
        "default_expiry_days": None,
        "inactivity_warning_days": 60,
        "inactivity_suspend_days": 90,
        "warning_intervals_days": [14, 7, 1],
        "archive_retention_days": 30,
    },
}


def deep_merge(base: Dict[str, Any], update_data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively deep merges update_data into a copy of base dictionary."""
    result = copy.deepcopy(base)
    for k, v in update_data.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def get_effective_profile(raw_profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Deep merges raw organization environment_profile with DEFAULT_ENVIRONMENT_PROFILE."""
    if not raw_profile or not isinstance(raw_profile, dict):
        return copy.deepcopy(DEFAULT_ENVIRONMENT_PROFILE)
    return deep_merge(DEFAULT_ENVIRONMENT_PROFILE, raw_profile)


def _matches_pattern(host: str, patterns: List[str]) -> bool:
    """Checks whether host matches any domain glob or exact pattern."""
    h = host.lower().strip()
    for pat in patterns:
        p = pat.lower().strip()
        if p == "*" or h == p:
            return True
        if fnmatch.fnmatch(h, p):
            return True
    return False


def validate_against_profile(manifest: Dict[str, Any], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Validates that manifest declarations DO NOT widen organization policy.
    Returns list of structured policy violations if any rule is broken.
    """
    violations: List[Dict[str, Any]] = []

    # 1. Shape Check
    shape = manifest.get("shape", "web-app")
    allowed_shapes = profile.get("allowed_shapes", ["web-app"])
    if shape not in allowed_shapes:
        violations.append({
            "code": "POLICY_VIOLATION",
            "error": "shape_not_allowed",
            "field": "shape",
            "rule": "allowed_shapes",
            "message": f"Shape '{shape}' is not permitted by organization environment profile.",
            "hint": f"Allowed shapes are: {allowed_shapes}.",
        })

    # 2. Runtime Check
    runtime = manifest.get("runtime", "node22")
    allowed_runtimes = profile.get("allowed_runtimes", ["node22"])
    if runtime not in allowed_runtimes:
        violations.append({
            "code": "POLICY_VIOLATION",
            "error": "runtime_not_allowed",
            "field": "runtime",
            "rule": "allowed_runtimes",
            "message": f"Runtime '{runtime}' is not permitted by organization environment profile.",
            "hint": f"Allowed runtimes are: {allowed_runtimes}.",
        })

    # 3. Capabilities Checks
    caps = manifest.get("capabilities") or {}
    allowed_caps = set(profile.get("capabilities", {}).get("allowed_capabilities", []))
    for cap_key in ["db", "files", "identity", "connectors", "ai"]:
        if caps.get(cap_key) and cap_key not in allowed_caps:
            violations.append({
                "code": "POLICY_VIOLATION",
                "error": "capability_not_allowed",
                "field": f"capabilities.{cap_key}",
                "rule": "allowed_capabilities",
                "message": f"Capability '{cap_key}' is disabled by organization environment profile.",
                "hint": f"Enabled capabilities are: {sorted(list(allowed_caps))}.",
            })

    # 4. Connectors & Identity Mode Checks
    conn_policy = profile.get("capabilities", {}).get("connectors", {})
    allowed_conns = conn_policy.get("allowed_connectors", ["*"])
    disabled_conns = set(conn_policy.get("disabled_connectors", []))
    global_allow_service = conn_policy.get("allow_service_identity", True)
    identity_rules = conn_policy.get("connector_identity_rules", {})

    connectors = caps.get("connectors") or []
    for idx, c in enumerate(connectors):
        if isinstance(c, dict):
            c_name = c.get("name") or c.get("id") or f"connector_{idx}"
            c_identity = c.get("identity") or c.get("acts_as") or "viewer"
        else:
            c_name = str(c)
            c_identity = "viewer"

        # Check disabled
        if c_name in disabled_conns:
            violations.append({
                "code": "POLICY_VIOLATION",
                "error": "connector_disabled",
                "field": f"capabilities.connectors.{idx}.name",
                "rule": "disabled_connectors",
                "message": f"Connector '{c_name}' is disabled organization-wide by policy.",
                "hint": f"Contact your organization administrator to re-enable '{c_name}'.",
            })
            continue

        # Check allowed allowlist
        if "*" not in allowed_conns and c_name not in allowed_conns:
            violations.append({
                "code": "POLICY_VIOLATION",
                "error": "connector_not_allowed",
                "field": f"capabilities.connectors.{idx}.name",
                "rule": "allowed_connectors",
                "message": f"Connector '{c_name}' is not in organization's allowed connectors list.",
                "hint": f"Allowed connectors are: {allowed_conns}.",
            })

        # Check service identity
        if c_identity == "service":
            if not global_allow_service:
                violations.append({
                    "code": "POLICY_VIOLATION",
                    "error": "service_identity_prohibited",
                    "field": f"capabilities.connectors.{idx}.identity",
                    "rule": "allow_service_identity",
                    "message": f"Service identity for connector '{c_name}' is prohibited by organization policy.",
                    "hint": "Set identity to 'viewer' or request policy exemption from organization admin.",
                })
            elif c_name in identity_rules:
                permitted_identities = identity_rules[c_name].get("allowed_identities", ["viewer"])
                if "service" not in permitted_identities:
                    violations.append({
                        "code": "POLICY_VIOLATION",
                        "error": "service_identity_prohibited",
                        "field": f"capabilities.connectors.{idx}.identity",
                        "rule": f"connector_identity_rules.{c_name}",
                        "message": f"Connector '{c_name}' only permits identities: {permitted_identities}.",
                        "hint": f"Change identity mode to one of: {permitted_identities}.",
                    })

    # 5. Egress Ceiling Checks (Allowlist & Denylist)
    egress_policy = profile.get("egress", {})
    allowed_domains = egress_policy.get("allowed_domains", ["*"])
    denied_domains = egress_policy.get("denied_domains", [])
    declared_egress = manifest.get("egress") or []

    for idx, e in enumerate(declared_egress):
        host = e.get("host") if isinstance(e, dict) else str(e)
        if not host:
            continue

        # Check denylist first
        if _matches_pattern(host, denied_domains):
            violations.append({
                "code": "POLICY_VIOLATION",
                "error": "egress_domain_denied",
                "field": f"egress.{idx}.host",
                "rule": "egress.denied_domains",
                "message": f"Egress destination '{host}' matches organization denylist pattern.",
                "hint": "Outbound connection to internal, metadata, or restricted domains is forbidden.",
            })
            continue

        # Check allowlist ceiling
        if "*" not in allowed_domains and not _matches_pattern(host, allowed_domains):
            violations.append({
                "code": "POLICY_VIOLATION",
                "error": "egress_domain_not_allowed",
                "field": f"egress.{idx}.host",
                "rule": "egress.allowed_domains",
                "message": f"Egress host '{host}' is outside organization egress allowlist ceiling.",
                "hint": f"Egress destination must match one of: {allowed_domains}.",
            })

    # 6. Sharing Policy Checks
    sharing_policy = profile.get("sharing", {})
    manifest_sharing = manifest.get("sharing") or {}
    allow_external = sharing_policy.get("allow_external_sharing", False)
    allow_guest = sharing_policy.get("allow_guest_users", False)

    if manifest_sharing.get("allow_external") and not allow_external:
        violations.append({
            "code": "POLICY_VIOLATION",
            "error": "external_sharing_prohibited",
            "field": "sharing.allow_external",
            "rule": "sharing.allow_external_sharing",
            "message": "External sharing with users outside the organization is prohibited by policy.",
            "hint": "Set 'sharing.allow_external' to false or share only with organization internal users.",
        })

    if manifest_sharing.get("allow_guests") and not allow_guest:
        violations.append({
            "code": "POLICY_VIOLATION",
            "error": "guest_users_prohibited",
            "field": "sharing.allow_guests",
            "rule": "sharing.allow_guest_users",
            "message": "Guest/anonymous viewer access is prohibited by organization policy.",
            "hint": "Set 'sharing.allow_guests' to false.",
        })

    # 7. AI Model & Budget Checks
    ai_policy = profile.get("ai", {})
    manifest_ai = caps.get("ai")
    if isinstance(manifest_ai, dict):
        allowed_models = ai_policy.get("allowed_models", [])
        requested_model = manifest_ai.get("model")
        if requested_model and allowed_models and requested_model not in allowed_models:
            violations.append({
                "code": "POLICY_VIOLATION",
                "error": "ai_model_not_allowed",
                "field": "capabilities.ai.model",
                "rule": "ai.allowed_models",
                "message": f"AI model '{requested_model}' is not in organization's allowed models list.",
                "hint": f"Permitted AI models are: {allowed_models}.",
            })

        max_budget = ai_policy.get("max_monthly_budget_usd", 50.0)
        requested_budget = manifest_ai.get("monthly_budget_usd")
        if requested_budget is not None and float(requested_budget) > float(max_budget):
            violations.append({
                "code": "POLICY_VIOLATION",
                "error": "quota_ceiling_exceeded",
                "field": "capabilities.ai.monthly_budget_usd",
                "rule": "ai.max_monthly_budget_usd",
                "message": f"Requested AI budget  exceeds organization ceiling .",
                "hint": f"Reduce 'capabilities.ai.monthly_budget_usd' to  or less.",
            })

    # 8. Quota Ceilings Checks
    quotas = profile.get("quotas", {})
    limits = manifest.get("limits") or {}

    quota_mappings = [
        ("memory_mb", "max_memory_mb", "limits.memory_mb"),
        ("request_timeout_s", "max_request_timeout_s", "limits.request_timeout_s"),
        ("db_max_mb", "max_db_size_mb", "limits.db_max_mb"),
        ("blob_max_mb", "max_blob_storage_mb", "limits.blob_max_mb"),
    ]

    for limit_key, quota_key, path in quota_mappings:
        req_val = limits.get(limit_key)
        if req_val is None and limit_key == "db_max_mb" and isinstance(caps.get("db"), dict):
            req_val = caps["db"].get("max_size_mb")
        if req_val is None and limit_key == "blob_max_mb" and isinstance(caps.get("files"), dict):
            req_val = caps["files"].get("max_mb")

        if req_val is not None and quota_key in quotas:
            max_allowed = quotas[quota_key]
            if req_val > max_allowed:
                violations.append({
                    "code": "POLICY_VIOLATION",
                    "error": "quota_ceiling_exceeded",
                    "field": path,
                    "rule": f"quotas.{quota_key}",
                    "message": f"Requested '{limit_key}' of {req_val} exceeds organization ceiling of {max_allowed}.",
                    "hint": f"Reduce '{path}' to {max_allowed} or less.",
                })

    return violations


def compute_effective_policy(profile: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Computes the effective policy (intersection of profile ceiling and manifest narrowing).
    Exposed via GET /v1/apps/{id}/effective-policy.
    """
    caps = manifest.get("capabilities") or {}
    limits = manifest.get("limits") or {}
    sharing = manifest.get("sharing") or {}
    quotas = profile.get("quotas", {})

    effective_limits = {
        "memory_mb": min(limits.get("memory_mb", 256), quotas.get("max_memory_mb", 512)),
        "request_timeout_s": min(limits.get("request_timeout_s", 30), quotas.get("max_request_timeout_s", 60)),
        "db_max_mb": min(limits.get("db_max_mb", 50), quotas.get("max_db_size_mb", 100)),
        "blob_max_mb": min(limits.get("blob_max_mb", 200), quotas.get("max_blob_storage_mb", 500)),
        "max_active_instances": 1,
    }

    raw_connectors = caps.get("connectors") or []
    effective_connectors = []
    for c in raw_connectors:
        if isinstance(c, dict):
            effective_connectors.append({
                "name": c.get("name") or c.get("id"),
                "identity": c.get("identity") or c.get("acts_as") or "viewer",
            })
        else:
            effective_connectors.append({"name": str(c), "identity": "viewer"})

    raw_egress = manifest.get("egress") or []
    effective_egress = [
        {"host": e.get("host") if isinstance(e, dict) else str(e)}
        for e in raw_egress
    ]

    return {
        "version": profile.get("version", "capsule/v1alpha1"),
        "shape": manifest.get("shape", "web-app"),
        "runtime": manifest.get("runtime", "node22"),
        "capabilities": {
            "db": bool(caps.get("db")),
            "files": bool(caps.get("files")),
            "identity": bool(caps.get("identity", True)),
            "ai": caps.get("ai") if isinstance(caps.get("ai"), dict) else bool(caps.get("ai")),
            "connectors": effective_connectors,
        },
        "egress": effective_egress,
        "sharing": {
            "default": sharing.get("default", profile.get("sharing", {}).get("default_scope", "org")),
            "allow_external": False if not profile.get("sharing", {}).get("allow_external_sharing") else bool(sharing.get("allow_external")),
            "allow_guests": False if not profile.get("sharing", {}).get("allow_guest_users") else bool(sharing.get("allow_guests")),
        },
        "limits": effective_limits,
    }


def evaluate_conditional_approval(
    manifest: Dict[str, Any],
    profile: Dict[str, Any],
    is_initial_publish: bool,
    audience_count: int,
    escalations: List[Dict[str, Any]],
) -> Tuple[bool, List[str]]:
    """
    Evaluates conditional approval rules (FR-032).
    Returns (requires_approval, reasons).
    """
    approvals_cfg = profile.get("approvals", {})
    threshold = approvals_cfg.get("audience_size_threshold", 10)
    sensitive_caps = set(approvals_cfg.get("sensitive_capabilities", ["connectors", "ai"]))
    req_service_id = approvals_cfg.get("require_approval_for_service_identity", True)
    req_org_sharing = approvals_cfg.get("require_approval_for_org_wide_sharing", False)

    reasons: List[str] = []

    # 1. Check version escalation first
    for esc in escalations:
        reasons.append(esc.get("reason", "Capability escalation detected"))

    # 2. Check audience size
    sharing = manifest.get("sharing") or {}
    is_org_wide = sharing.get("default") == "org"

    if is_org_wide and req_org_sharing and audience_count > threshold:
        reasons.append(f"Audience size ({audience_count} users) exceeds small-app auto-publish threshold ({threshold}).")

    # 3. Check service identity on any connector
    caps = manifest.get("capabilities") or {}
    connectors = caps.get("connectors") or []
    for c in connectors:
        ident = c.get("identity") or c.get("acts_as") if isinstance(c, dict) else "viewer"
        c_name = c.get("name") if isinstance(c, dict) else str(c)
        if ident == "service" and req_service_id:
            reasons.append(f"Connector '{c_name}' requests service identity.")

    # 4. Sensitive capabilities check for initial publish
    if is_initial_publish:
        for cap_key in sensitive_caps:
            if caps.get(cap_key):
                # Service identity connectors were already flagged above; only flag if not viewer-only
                if cap_key == "connectors":
                    for c in connectors:
                        ident = c.get("identity") or c.get("acts_as") if isinstance(c, dict) else "viewer"
                        if ident == "service":
                            pass  # already flagged
                elif cap_key == "ai":
                    reasons.append(f"Initial publication requests sensitive capability '{cap_key}'.")

    requires_approval = len(reasons) > 0
    return requires_approval, reasons


def compute_profile_diff(old_profile: Dict[str, Any], new_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Computes structured before/after diff for profile updates."""
    changes = []

    old_rt = set(old_profile.get("allowed_runtimes", []))
    new_rt = set(new_profile.get("allowed_runtimes", []))
    if old_rt != new_rt:
        changes.append({
            "section": "allowed_runtimes",
            "old": list(old_rt),
            "new": list(new_rt),
            "type": "modified",
        })

    old_conn = old_profile.get("capabilities", {}).get("connectors", {})
    new_conn = new_profile.get("capabilities", {}).get("connectors", {})
    if old_conn != new_conn:
        changes.append({
            "section": "connectors",
            "old": old_conn,
            "new": new_conn,
            "type": "modified",
        })

    old_egress = old_profile.get("egress", {})
    new_egress = new_profile.get("egress", {})
    if old_egress != new_egress:
        changes.append({
            "section": "egress",
            "old": old_egress,
            "new": new_egress,
            "type": "modified",
        })

    old_quotas = old_profile.get("quotas", {})
    new_quotas = new_profile.get("quotas", {})
    for q_key, new_q in new_quotas.items():
        old_q = old_quotas.get(q_key)
        if old_q != new_q:
            changes.append({
                "section": f"quotas.{q_key}",
                "old": old_q,
                "new": new_q,
                "type": "tightened" if (old_q is not None and new_q is not None and new_q < old_q) else "loosened",
            })

    return {
        "has_changes": len(changes) > 0,
        "changes_count": len(changes),
        "changes": changes,
    }
