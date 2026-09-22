"""
Audit Webhook Dispatcher
Dispatches audit events to external logging and SIEM systems (Datadog, Splunk, etc.)
with HMAC-SHA256 signature verification.
"""
import hmac
import hashlib
import json
import uuid
from typing import Any, Dict, Optional
import httpx
import logging

logger = logging.getLogger("audit.webhook")


def sign_audit_webhook_payload(payload_bytes: bytes, secret: str) -> str:
    """
    Computes HMAC-SHA256 hex digest for the webhook payload.
    """
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


async def dispatch_audit_webhook(
    url: str,
    secret_token: Optional[str],
    event_dict: Dict[str, Any],
    timeout_seconds: float = 5.0,
) -> bool:
    """
    Asynchronously delivers an audit event to a webhook destination.
    """
    try:
        body = json.dumps(event_dict, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "CapsulePlatform-AuditWebhook/1.0",
            "X-Capsule-Delivery": str(uuid.uuid4()),
            "X-Capsule-Event": event_dict.get("action", "audit.event"),
        }
        if secret_token:
            sig = sign_audit_webhook_payload(body, secret_token)
            headers["X-Capsule-Signature"] = f"sha256={sig}"

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(url, content=body, headers=headers)
            if resp.status_code >= 400:
                logger.warning(
                    f"Audit webhook delivery failed to {url}: HTTP {resp.status_code}"
                )
                return False
            return True
    except Exception as exc:
        logger.error(f"Audit webhook delivery error to {url}: {exc}")
        return False
