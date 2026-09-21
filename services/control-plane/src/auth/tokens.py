"""
Scoped Publish Token Service.
Issues and verifies short-lived publish tokens (per-app or per-user).
"""
import os
import time
import uuid
from typing import Any, Dict, Optional
import jwt
from .provider import AuthenticationError, TokenExpiredError

DEFAULT_SECRET = "control-plane-dev-jwt-secret-do-not-use-in-prod"


class PublishTokenService:
    """Handles issuance and validation of scoped publish tokens."""

    def __init__(self, secret: Optional[str] = None):
        self.secret = secret or os.environ.get("JWT_SECRET", DEFAULT_SECRET)
        self.algorithm = "HS256"

    def create_publish_token(
        self,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        app_id: Optional[uuid.UUID] = None,
        expires_in_seconds: int = 3600,
    ) -> Dict[str, Any]:
        """Create a scoped publish token."""
        now = int(time.time())
        scope = "publish:app" if app_id else "publish:user"
        jti = str(uuid.uuid4())

        payload = {
            "sub": str(user_id),
            "org_id": str(organization_id),
            "app_id": str(app_id) if app_id else None,
            "scope": scope,
            "token_type": "publish_token",
            "jti": jti,
            "iat": now,
            "exp": now + expires_in_seconds,
        }

        token = jwt.encode(payload, self.secret, algorithm=self.algorithm)
        return {
            "token": token,
            "token_type": "Bearer",
            "expires_in": expires_in_seconds,
            "scope": scope,
            "app_id": str(app_id) if app_id else None,
            "jti": jti,
        }

    def verify_publish_token(self, token: str) -> Dict[str, Any]:
        """Verify a scoped publish token."""
        try:
            payload = jwt.decode(
                token,
                self.secret,
                algorithms=[self.algorithm],
                options={"require": ["sub", "org_id", "scope", "exp"]},
            )
            if payload.get("token_type") != "publish_token":
                raise AuthenticationError("Token is not a publish token.")
            return payload
        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError("Publish token has expired.") from e
        except jwt.InvalidTokenError as e:
            raise AuthenticationError(f"Invalid publish token: {e}") from e
