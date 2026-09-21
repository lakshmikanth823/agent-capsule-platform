import os
from typing import Any, Dict, Optional
import httpx
from .base import BaseConnector


class SlackPostConnector(BaseConnector):
    name = "slack.post"

    async def invoke(
        self,
        payload: Dict[str, Any],
        credential: Any,
        identity: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Posts a message to Slack via chat.postMessage or webhook.
        Attaches the credential at the egress layer.
        """
        if not credential:
            raise ValueError("No credential was attached by broker for slack.post")

        # Resolve channel from payload or manifest context
        channel = payload.get("channel")
        if not channel and context and "channel" in context:
            channel = context["channel"]
        if not channel:
            channel = "#general"

        text = payload.get("text") or payload.get("message")
        if not text:
            raise ValueError("Missing 'text' or 'message' field in payload")

        # Slack API endpoint: can be overridden in tests via SLACK_API_URL
        slack_api_url = os.environ.get("SLACK_API_URL") or "https://slack.com/api/chat.postMessage"

        headers = {
            "Content-Type": "application/json; charset=utf-8",
        }

        request_body: Dict[str, Any] = {
            "channel": channel,
            "text": text,
        }

        if "blocks" in payload:
            request_body["blocks"] = payload["blocks"]

        bot_token = None
        webhook_url = None
        if isinstance(credential, dict):
            bot_token = credential.get("bot_token") or credential.get("token")
            webhook_url = credential.get("webhook_url")
        elif isinstance(credential, str):
            if credential.startswith("https://hooks.slack.com/"):
                webhook_url = credential
            else:
                bot_token = credential

        if bot_token:
            headers["Authorization"] = f"Bearer {bot_token}"
            target_url = slack_api_url
        elif webhook_url:
            target_url = webhook_url
        else:
            raise ValueError("Invalid Slack credential: expected bot_token or webhook_url")

        # Dispatch HTTP request to external Slack service (egress layer)
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(target_url, json=request_body, headers=headers)
                status_code = response.status_code
                try:
                    resp_json = response.json()
                except Exception:
                    resp_json = {"raw": response.text}

                if status_code >= 400 or (isinstance(resp_json, dict) and resp_json.get("ok") is False):
                    err_msg = resp_json.get("error", f"Slack API returned status {status_code}")
                    return {
                        "connector": self.name,
                        "status": "failed",
                        "ok": False,
                        "error": err_msg,
                        "channel": channel,
                    }

                return {
                    "connector": self.name,
                    "status": "success",
                    "ok": True,
                    "channel": channel,
                    "ts": resp_json.get("ts", "1234567890.123456"),
                    "message": resp_json.get("message"),
                }
            except httpx.RequestError as exc:
                return {
                    "connector": self.name,
                    "status": "failed",
                    "ok": False,
                    "error": f"Network error contacting Slack: {str(exc)}",
                    "channel": channel,
                }
