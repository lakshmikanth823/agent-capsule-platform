"""
Manifest Validator for Software Capsules in Control Plane.
Enforces JSON Schema Draft 2020-12 and semantic checks identical to @capsule/manifest-schema.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import jsonschema
from jsonschema import Draft202012Validator

HOSTNAME_REGEX = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)
IP_REGEX = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$|^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$")
ID_REGEX = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ROLE_REGEX = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# Find and load the shared schema
def _load_schema() -> Dict[str, Any]:
    candidates = [
        Path(__file__).resolve().parents[4] / "packages" / "manifest-schema" / "schema" / "capsule.manifest.schema.json",
        Path(__file__).resolve().parents[3] / "packages" / "manifest-schema" / "schema" / "capsule.manifest.schema.json",
        Path("packages/manifest-schema/schema/capsule.manifest.schema.json").resolve(),
    ]
    for p in candidates:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError("Could not locate capsule.manifest.schema.json")

SCHEMA_JSON = _load_schema()
SCHEMA_VALIDATOR = Draft202012Validator(SCHEMA_JSON)


def validate_manifest(input_data: Any) -> Dict[str, Any]:
    """Pure validation function for Capsule manifests."""
    checks: List[Dict[str, Any]] = []
    required_approvals: List[str] = []
    warnings: List[str] = []

    # 1. Basic Type Check
    if not isinstance(input_data, dict):
        check = {
            "name": "basic_type",
            "status": "fail",
            "code": "invalid_manifest",
            "path": None,
            "message": "Manifest must be a non-null object.",
            "hint": "Provide a valid YAML/JSON document with top-level fields: apiVersion, id, name, shape, runtime.",
        }
        return {
            "valid": False,
            "errors": [check],
            "checks": [check],
            "required_approvals": [],
            "warnings": [],
            "effective_manifest": None,
        }

    manifest = dict(input_data)

    # 2. Schema Validation (Draft 2020-12)
    schema_errors = sorted(SCHEMA_VALIDATOR.iter_errors(manifest), key=lambda e: e.path)
    if schema_errors:
        for err in schema_errors:
            path = ".".join(str(p) for p in err.path) if err.path else None
            message = err.message
            hint = "Fix the field according to capsule.manifest.schema.json."

            if err.validator == "required":
                missing = err.validator_value[0] if isinstance(err.validator_value, list) else str(err.message)
                # match property name from message e.g. "'id' is a required property"
                match = re.search(r"'([^']+)' is a required property", err.message)
                if match:
                    missing = match.group(1)
                path = f"{path}.{missing}" if path else missing
                message = f"Missing required property '{missing}'."
                hint = f"Add the required '{missing}' property to your manifest."
            elif err.validator == "additionalProperties":
                match = re.search(r"Additional properties are not allowed \('([^']+)'", err.message)
                extra = match.group(1) if match else "unknown"
                path = f"{path}.{extra}" if path else extra
                message = f"Unrecognized property '{extra}'."
                hint = f"Remove '{extra}'. Unknown properties are not permitted."
            elif err.validator == "const":
                expected = err.validator_value
                message = f"Value must be '{expected}'."
                hint = f"Change value to '{expected}'."
            elif err.validator == "pattern":
                if path == "id":
                    message = f"Invalid capsule ID '{manifest.get('id')}'."
                    hint = "Capsule ID must be 1-63 lowercase alphanumeric characters and hyphens (e.g. leave-tracker)."
                elif path and path.startswith("roles"):
                    message = "Invalid role name format."
                    hint = "Role names must start with lowercase letter and use snake_case (e.g. hr_manager)."
                else:
                    message = f"Value at '{path}' does not match required pattern."
                    hint = f"Ensure '{path}' conforms to pattern: {err.validator_value}"

            checks.append({
                "name": "schema_validation",
                "status": "fail",
                "code": "invalid_manifest",
                "path": path,
                "message": message,
                "hint": hint,
            })
    else:
        checks.append({
            "name": "schema_validation",
            "status": "pass",
            "code": "schema_valid",
            "path": None,
            "message": "Manifest conforms to JSON Schema Draft 2020-12.",
        })

    # 3. Semantic Checks: Shape
    shape = manifest.get("shape")
    if shape is not None:
        if shape != "web-app":
            checks.append({
                "name": "shape_check",
                "status": "fail",
                "code": "unsupported_shape",
                "path": "shape",
                "message": f"Unsupported shape '{shape}'.",
                "hint": "Set 'shape' to 'web-app'. Only web-app is supported in Alpha/MVP.",
            })
        else:
            checks.append({
                "name": "shape_check",
                "status": "pass",
                "code": "shape_valid",
                "path": "shape",
                "message": "Shape 'web-app' is valid.",
            })

    # 4. Semantic Checks: Runtime
    runtime = manifest.get("runtime")
    if runtime is not None:
        if runtime != "node22":
            checks.append({
                "name": "runtime_check",
                "status": "fail",
                "code": "unsupported_runtime",
                "path": "runtime",
                "message": f"Unsupported runtime '{runtime}'.",
                "hint": "Set 'runtime' to 'node22'. Only node22 is supported in Alpha/MVP.",
            })
        else:
            checks.append({
                "name": "runtime_check",
                "status": "pass",
                "code": "runtime_valid",
                "path": "runtime",
                "message": "Runtime 'node22' is valid.",
            })

    # 5. Semantic Checks: ID Format
    cid = manifest.get("id")
    if cid is not None and isinstance(cid, str):
        if not ID_REGEX.match(cid):
            checks.append({
                "name": "id_check",
                "status": "fail",
                "code": "invalid_manifest",
                "path": "id",
                "message": f"Invalid capsule ID '{cid}'.",
                "hint": "Capsule ID must be 1-63 lowercase alphanumeric characters and hyphens (e.g. leave-tracker).",
            })
        else:
            checks.append({
                "name": "id_check",
                "status": "pass",
                "code": "id_valid",
                "path": "id",
                "message": "Capsule ID format is valid.",
            })

    # 6. Semantic Checks: Roles Uniqueness & Format
    roles = manifest.get("roles")
    declared_roles = set()
    if isinstance(roles, list):
        seen_roles = set()
        for i, role in enumerate(roles):
            if isinstance(role, str):
                if not ROLE_REGEX.match(role):
                    checks.append({
                        "name": f"role_format_{i}",
                        "status": "fail",
                        "code": "invalid_manifest",
                        "path": f"roles.{i}",
                        "message": f"Invalid role name '{role}'.",
                        "hint": "Role names must start with lowercase letter and use snake_case (e.g. hr_manager).",
                    })
                if role in seen_roles:
                    checks.append({
                        "name": f"role_unique_{i}",
                        "status": "fail",
                        "code": "invalid_manifest",
                        "path": f"roles.{i}",
                        "message": f"Duplicate role '{role}'.",
                        "hint": f"Remove duplicate role '{role}' from the roles list.",
                    })
                seen_roles.add(role)
                declared_roles.add(role)

    # 7. Semantic Checks: Capabilities & Connectors
    capabilities = manifest.get("capabilities")
    if isinstance(capabilities, dict):
        connectors = capabilities.get("connectors")
        if isinstance(connectors, list):
            for i, conn in enumerate(connectors):
                if isinstance(conn, dict):
                    name = conn.get("name", f"connector_{i}")
                    identity = conn.get("identity", "viewer")

                    if identity not in ("viewer", "service"):
                        checks.append({
                            "name": f"connector_identity_{name}",
                            "status": "fail",
                            "code": "invalid_manifest",
                            "path": f"capabilities.connectors.{i}.identity",
                            "message": f"Invalid connector identity '{identity}'.",
                            "hint": "Connector identity must be either 'viewer' or 'service'.",
                        })
                    elif identity == "service":
                        required_approvals.append(f"connector:{name}:service_identity")
                        checks.append({
                            "name": f"connector_approval_{name}",
                            "status": "fail",
                            "code": "approval_required",
                            "path": f"capabilities.connectors.{i}.identity",
                            "message": f"Connector '{name}' requests 'service' identity which requires owner approval.",
                            "hint": "An organization administrator or app owner must approve 'service' identity.",
                        })

                    # Role check
                    req_roles = conn.get("required_roles")
                    if isinstance(req_roles, list):
                        for r in req_roles:
                            if r not in declared_roles:
                                checks.append({
                                    "name": f"connector_role_{name}_{r}",
                                    "status": "fail",
                                    "code": "invalid_manifest",
                                    "path": f"capabilities.connectors.{i}.required_roles",
                                    "message": f"Connector '{name}' requires undeclared role '{r}'.",
                                    "hint": f"Add '{r}' to the top-level 'roles' list in capsule.manifest.yaml.",
                                })

    # 8. Semantic Checks: Egress
    egress = manifest.get("egress")
    if egress is None or len(egress) == 0:
        checks.append({
            "name": "egress_default_deny",
            "status": "pass",
            "code": "egress_denied_default",
            "path": "egress",
            "message": "Outbound egress is denied by default.",
        })
    elif isinstance(egress, list):
        for i, entry in enumerate(egress):
            if isinstance(entry, dict):
                host = entry.get("host")
                if not host or not isinstance(host, str):
                    checks.append({
                        "name": f"egress_entry_{i}",
                        "status": "fail",
                        "code": "invalid_manifest",
                        "path": f"egress.{i}.host",
                        "message": "Egress entry missing host.",
                        "hint": "Provide a valid FQDN in the 'host' field (e.g. api.github.com).",
                    })
                    continue

                if "*" in host:
                    checks.append({
                        "name": f"egress_wildcard_{i}",
                        "status": "fail",
                        "code": "egress_denied",
                        "path": f"egress.{i}.host",
                        "message": f"Wildcard host '{host}' is prohibited.",
                        "hint": "Specify exact fully qualified domain names (e.g. api.github.com).",
                    })
                elif IP_REGEX.match(host):
                    checks.append({
                        "name": f"egress_ip_{i}",
                        "status": "fail",
                        "code": "egress_denied",
                        "path": f"egress.{i}.host",
                        "message": f"Direct IP address '{host}' is prohibited.",
                        "hint": "Use fully qualified domain names instead of IP addresses.",
                    })
                elif not HOSTNAME_REGEX.match(host):
                    checks.append({
                        "name": f"egress_format_{i}",
                        "status": "fail",
                        "code": "egress_denied",
                        "path": f"egress.{i}.host",
                        "message": f"Host '{host}' is not a valid FQDN.",
                        "hint": "Do not include protocols (https://) or paths. Use format: hostname.domain.tld",
                    })
                else:
                    checks.append({
                        "name": f"egress_entry_{i}",
                        "status": "pass",
                        "code": "egress_allowed",
                        "path": f"egress.{i}.host",
                        "message": f"Egress host '{host}' format valid.",
                    })
        warnings.append("Non-empty egress declaration requires administrative monitoring.")

    # 9. Semantic Checks: Resource Limits
    limits = manifest.get("limits")
    if isinstance(limits, dict):
        mem = limits.get("memory_mb")
        if mem is not None and isinstance(mem, (int, float)) and mem > 512:
            checks.append({
                "name": "limit_memory",
                "status": "fail",
                "code": "quota_exceeded",
                "path": "limits.memory_mb",
                "message": f"Requested memory {mem}MB exceeds Alpha quota of 512MB.",
                "hint": "Reduce 'limits.memory_mb' to 512 or less.",
            })

        timeout = limits.get("request_timeout_s")
        if timeout is not None and isinstance(timeout, (int, float)) and timeout > 60:
            checks.append({
                "name": "limit_timeout",
                "status": "fail",
                "code": "quota_exceeded",
                "path": "limits.request_timeout_s",
                "message": f"Requested timeout {timeout}s exceeds Alpha quota of 60s.",
                "hint": "Reduce 'limits.request_timeout_s' to 60 or less.",
            })

        instances = limits.get("max_active_instances")
        if instances is not None and isinstance(instances, int) and instances > 1:
            checks.append({
                "name": "limit_instances",
                "status": "fail",
                "code": "quota_exceeded",
                "path": "limits.max_active_instances",
                "message": f"Requested instances {instances} exceeds Alpha maximum of 1.",
                "hint": "Set 'limits.max_active_instances' to 1 for Alpha single-instance execution.",
            })

    # Overall validity: no failed checks
    errors = [c for c in checks if c["status"] == "fail"]
    valid = len(errors) == 0

    effective_manifest = None
    if valid:
        normalized_connectors = []
        if isinstance(manifest.get("capabilities"), dict) and isinstance(manifest["capabilities"].get("connectors"), list):
            for c in manifest["capabilities"]["connectors"]:
                nc = dict(c)
                nc.setdefault("identity", "viewer")
                normalized_connectors.append(nc)

        effective_manifest = {
            "apiVersion": manifest.get("apiVersion", "capsule/v1alpha1"),
            "id": manifest.get("id"),
            "name": manifest.get("name"),
            "shape": manifest.get("shape", "web-app"),
            "runtime": manifest.get("runtime", "node22"),
            "roles": list(manifest.get("roles", [])),
            "capabilities": {
                **manifest.get("capabilities", {}),
                "connectors": normalized_connectors,
            } if manifest.get("capabilities") else None,
            "egress": list(manifest.get("egress", [])),
            "sharing": manifest.get("sharing", {"default": "org"}),
            "limits": {
                "cpu": manifest.get("limits", {}).get("cpu", "small"),
                "memory_mb": manifest.get("limits", {}).get("memory_mb", 256),
                "request_timeout_s": manifest.get("limits", {}).get("request_timeout_s", 30),
                "db_max_mb": manifest.get("limits", {}).get("db_max_mb", 50),
                "blob_max_mb": manifest.get("limits", {}).get("blob_max_mb", 200),
                "max_active_instances": 1,
            },

        }

    return {
        "valid": valid,
        "errors": errors,
        "checks": checks,
        "required_approvals": required_approvals,
        "warnings": warnings,
        "effective_manifest": effective_manifest,
    }
