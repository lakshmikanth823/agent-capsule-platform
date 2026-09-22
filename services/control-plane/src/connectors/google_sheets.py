"""
Google Sheets Read Connector (sheets.read)
Implements Prompt 25, PRD FR-024 / FR-025, TRD Section 21:
- Acts as the VIEWER using per-user OAuth tokens.
- Restricts access to declared spreadsheet IDs when specified in manifest.
- Attaches the viewer's OAuth token at the egress proxy layer.
- Handles token auto-refresh and revocation.
- The calling capsule only receives data values; never the raw token.
"""
import os
import time
from typing import Any, Dict, Optional, List
import httpx
from .base import BaseConnector


class GoogleSheetsReadConnector(BaseConnector):
    name = "sheets.read"

    async def invoke(
        self,
        payload: Dict[str, Any],
        credential: Any,
        identity: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Reads values from a Google Spreadsheet on behalf of the viewer.
        Attaches the viewer's OAuth token at the egress layer.
        """
        if not credential:
            raise ValueError("No viewer credential was attached by broker for sheets.read")

        # 1. Resolve spreadsheet ID and range from payload
        spreadsheet_id = payload.get("spreadsheet_id") or payload.get("spreadsheetId")
        if not spreadsheet_id:
            raise ValueError("Missing required 'spreadsheet_id' or 'spreadsheetId' in payload")

        range_param = payload.get("range") or "A1:Z100"

        # 2. Enforce manifest spreadsheet restriction if declared
        if context and "spreadsheet_ids" in context:
            allowed_ids = context.get("spreadsheet_ids")
            if isinstance(allowed_ids, list) and len(allowed_ids) > 0:
                if spreadsheet_id not in allowed_ids:
                    return {
                        "connector": self.name,
                        "status": "failed",
                        "code": "SPREADSHEET_NOT_ALLOWED",
                        "error": f"Access to spreadsheet '{spreadsheet_id}' is not permitted by the application manifest.",
                        "allowed_spreadsheets": allowed_ids,
                    }

        # 3. Extract tokens from credential
        access_token = None
        refresh_token = None
        expires_at = None
        client_id = None
        client_secret = None

        if isinstance(credential, dict):
            access_token = credential.get("access_token") or credential.get("token")
            refresh_token = credential.get("refresh_token")
            expires_at = credential.get("expires_at")
            client_id = credential.get("client_id")
            client_secret = credential.get("client_secret")
        elif isinstance(credential, str):
            access_token = credential

        if not access_token and not refresh_token:
            raise ValueError("Invalid Google Sheets credential: missing access_token or refresh_token")

        # Check if token is expired and refresh token is available
        token_url = os.environ.get("GOOGLE_OAUTH_TOKEN_URL") or "https://oauth2.googleapis.com/token"
        now = time.time()
        if (not access_token or (expires_at and expires_at < now)) and refresh_token:
            refreshed = await self._refresh_access_token(
                token_url=token_url,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
            )
            if refreshed:
                access_token = refreshed.get("access_token")
                # Update credential dictionary in place so caller/DAL can persist updated token
                if isinstance(credential, dict):
                    credential["access_token"] = access_token
                    credential["expires_at"] = now + refreshed.get("expires_in", 3600)
                    credential["_refreshed"] = True

        if not access_token:
            return {
                "connector": self.name,
                "status": "failed",
                "code": "OAUTH_TOKEN_REVOKED",
                "error": "Google OAuth token has expired or been revoked. Please re-authenticate.",
            }

        # 4. Dispatch request to Google Sheets API
        sheets_api_base = os.environ.get("GOOGLE_SHEETS_API_URL") or "https://sheets.googleapis.com/v4/spreadsheets"
        target_url = f"{sheets_api_base.rstrip('/')}/{spreadsheet_id}/values/{range_param}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(target_url, headers=headers)
                
                # Check for 401 Unauthorized (attempt refresh if possible)
                if response.status_code == 401 and refresh_token:
                    refreshed = await self._refresh_access_token(
                        token_url=token_url,
                        refresh_token=refresh_token,
                        client_id=client_id,
                        client_secret=client_secret,
                    )
                    if refreshed:
                        access_token = refreshed.get("access_token")
                        if isinstance(credential, dict):
                            credential["access_token"] = access_token
                            credential["expires_at"] = time.time() + refreshed.get("expires_in", 3600)
                            credential["_refreshed"] = True
                        headers["Authorization"] = f"Bearer {access_token}"
                        response = await client.get(target_url, headers=headers)

                status_code = response.status_code
                try:
                    resp_json = response.json()
                except Exception:
                    resp_json = {}

                # Map Google API errors
                if status_code == 403:
                    return {
                        "connector": self.name,
                        "status": "failed",
                        "code": "PERMISSION_DENIED",
                        "error": resp_json.get("error", {}).get("message", "The viewer does not have permission to access this spreadsheet."),
                        "spreadsheet_id": spreadsheet_id,
                    }

                if status_code == 401:
                    return {
                        "connector": self.name,
                        "status": "failed",
                        "code": "OAUTH_TOKEN_REVOKED",
                        "error": "Google OAuth token is invalid or has been revoked.",
                        "spreadsheet_id": spreadsheet_id,
                    }

                if status_code == 404:
                    return {
                        "connector": self.name,
                        "status": "failed",
                        "code": "NOT_FOUND",
                        "error": f"Spreadsheet '{spreadsheet_id}' was not found.",
                        "spreadsheet_id": spreadsheet_id,
                    }

                if status_code >= 400:
                    return {
                        "connector": self.name,
                        "status": "failed",
                        "code": "GOOGLE_API_ERROR",
                        "error": resp_json.get("error", {}).get("message", f"Google API returned HTTP {status_code}"),
                        "spreadsheet_id": spreadsheet_id,
                    }

                # 5. Success: return only data values, never the token
                return {
                    "connector": self.name,
                    "status": "success",
                    "spreadsheet_id": spreadsheet_id,
                    "range": resp_json.get("range", range_param),
                    "major_dimension": resp_json.get("majorDimension", "ROWS"),
                    "values": resp_json.get("values", []),
                }

            except httpx.RequestError as exc:
                return {
                    "connector": self.name,
                    "status": "failed",
                    "code": "NETWORK_ERROR",
                    "error": f"Failed to communicate with Google Sheets service: {str(exc)}",
                    "spreadsheet_id": spreadsheet_id,
                }

    async def _refresh_access_token(
        self,
        token_url: str,
        refresh_token: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Refreshes the Google OAuth access token using refresh_token grant."""
        post_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id or os.environ.get("GOOGLE_CLIENT_ID", "mock-client-id"),
            "client_secret": client_secret or os.environ.get("GOOGLE_CLIENT_SECRET", "mock-client-secret"),
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(token_url, data=post_data)
                if resp.status_code == 200:
                    return resp.json()
                return None
            except Exception:
                return None
