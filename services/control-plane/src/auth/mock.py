"""
Mock OIDC Provider for local development and automated testing.
Provides two pre-configured fake users (Alice - owner, Bob - colleague/user),
plus Charlie (external org user for cross-user security tests).
"""
import time
from typing import Any, Dict
from .provider import OIDCProvider, AuthenticationError, TokenExpiredError

MOCK_USERS = {
    "mock-alice-token": {
        "sub": "mock-sub-alice",
        "email": "alice@example.com",
        "name": "Alice Owner",
        "iss": "mock:oidc",
        "org_slug": "acme-corp",
        "platform_role": "owner",
    },
    "mock-bob-token": {
        "sub": "mock-sub-bob",
        "email": "bob@example.com",
        "name": "Bob Colleague",
        "iss": "mock:oidc",
        "org_slug": "acme-corp",
        "platform_role": "user",
    },
    "mock-charlie-token": {
        "sub": "mock-sub-charlie",
        "email": "charlie@other.com",
        "name": "Charlie Other",
        "iss": "mock:oidc",
        "org_slug": "other-corp",
        "platform_role": "owner",
    },
}


class MockOIDCProvider(OIDCProvider):
    """Mock identity provider that returns predefined claims for known mock tokens."""

    async def verify_token(self, token: str) -> Dict[str, Any]:
        if token == "mock-expired-token":
            raise TokenExpiredError("Token has expired.")

        if token in MOCK_USERS:
            claims = dict(MOCK_USERS[token])
            claims["exp"] = int(time.time()) + 3600
            return claims

        # Check if token is prefixed with "mock:"
        if token.startswith("mock:"):
            email = token.split(":", 1)[1]
            return {
                "sub": f"mock-sub-{email}",
                "email": email,
                "name": email.split("@")[0].capitalize(),
                "iss": "mock:oidc",
                "org_slug": "acme-corp",
                "platform_role": "user",
                "exp": int(time.time()) + 3600,
            }

        raise AuthenticationError("Invalid mock token.")
