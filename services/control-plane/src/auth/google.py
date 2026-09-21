"""
Google OIDC Provider configurable by environment variables.
"""
import os
import time
from typing import Any, Dict, Optional
import jwt
from jwt import PyJWKClient
from .provider import OIDCProvider, AuthenticationError, TokenExpiredError


class GoogleOIDCProvider(OIDCProvider):
    """Verifies Google OIDC ID tokens."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        issuer_url: Optional[str] = None,
        jwks_url: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("GOOGLE_CLIENT_ID", "")
        self.issuer_url = issuer_url or os.environ.get("OIDC_ISSUER_URL", "https://accounts.google.com")
        self.jwks_url = jwks_url or os.environ.get("OIDC_JWKS_URL", "https://www.googleapis.com/oauth2/v3/certs")
        self._jwks_client: Optional[PyJWKClient] = None

    def _get_jwks_client(self) -> PyJWKClient:
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self.jwks_url)
        return self._jwks_client

    async def verify_token(self, token: str) -> Dict[str, Any]:
        if not self.client_id:
            raise AuthenticationError("Google OIDC is not configured (missing GOOGLE_CLIENT_ID).")

        try:
            jwks_client = self._get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=[self.issuer_url, "accounts.google.com"],
            )
            return payload
        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError("Google OIDC token has expired.") from e
        except Exception as e:
            raise AuthenticationError(f"Google OIDC verification failed: {e}") from e
