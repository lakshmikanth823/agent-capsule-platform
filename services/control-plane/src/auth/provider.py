"""
Base OIDC Provider interface and authentication exceptions.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


class TokenExpiredError(AuthenticationError):
    """Raised when token is expired."""
    pass


class OIDCProvider(ABC):
    """Abstract interface for OIDC identity providers."""

    @abstractmethod
    async def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify token and return decoded claims (email, sub, name, iss, etc.)."""
        pass
