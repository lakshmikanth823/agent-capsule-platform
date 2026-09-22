"""
Generic OpenID Connect (OIDC) Service with Discovery, JWKS Validation, and Security Protections.
"""
import os
import time
import uuid
import secrets
from typing import Any, Dict, Optional, Tuple
import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

DEFAULT_SECRET = "control-plane-dev-jwt-secret-do-not-use-in-prod"


class OIDCError(Exception):
    """Base exception for OIDC errors."""
    pass


class OIDCService:
    """Handles OIDC discovery, state/nonce generation, code exchange, and ID token verification."""

    # Simple TTL cache for discovery docs and JWKS
    _cache: Dict[str, Tuple[float, Any]] = {}
    CACHE_TTL = 3600  # 1 hour

    def __init__(self, jwt_secret: Optional[str] = None):
        self.jwt_secret = jwt_secret or os.environ.get("JWT_SECRET", DEFAULT_SECRET)

    @classmethod
    def _get_from_cache(cls, key: str) -> Optional[Any]:
        if key in cls._cache:
            ts, val = cls._cache[key]
            if time.time() - ts < cls.CACHE_TTL:
                return val
            del cls._cache[key]
        return None

    @classmethod
    def _set_in_cache(cls, key: str, val: Any) -> None:
        cls._cache[key] = (time.time(), val)

    async def discover(self, discovery_url: str) -> Dict[str, Any]:
        """Fetch and cache OIDC discovery document."""
        cached = self._get_from_cache(discovery_url)
        if cached:
            return cached

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(discovery_url)
                resp.raise_for_status()
                data = resp.json()
                self._set_in_cache(discovery_url, data)
                return data
            except Exception as e:
                raise OIDCError(f"Failed to fetch OIDC discovery document from {discovery_url}: {e}") from e

    async def get_jwks(self, jwks_uri: str) -> Dict[str, Any]:
        """Fetch and cache JWKS keys."""
        cached = self._get_from_cache(jwks_uri)
        if cached:
            return cached

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(jwks_uri)
                resp.raise_for_status()
                data = resp.json()
                self._set_in_cache(jwks_uri, data)
                return data
            except Exception as e:
                raise OIDCError(f"Failed to fetch JWKS from {jwks_uri}: {e}") from e

    def generate_state_and_nonce(
        self,
        org_id: uuid.UUID,
        target_app: Optional[str] = None,
        return_to: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Generates a cryptographically signed state token and random nonce.
        State encodes the request context and prevents CSRF.
        """
        nonce = secrets.token_urlsafe(32)
        now = int(time.time())
        state_payload = {
            "org_id": str(org_id),
            "target_app": target_app,
            "return_to": return_to,
            "nonce": nonce,
            "iat": now,
            "exp": now + 600,  # 10 minute lifetime
            "type": "oidc_state",
        }
        state_token = jwt.encode(state_payload, self.jwt_secret, algorithm="HS256")
        return state_token, nonce

    def verify_state(self, state_token: str) -> Dict[str, Any]:
        """Verifies state token signature and expiration."""
        try:
            payload = jwt.decode(
                state_token,
                self.jwt_secret,
                algorithms=["HS256"],
                options={"require": ["org_id", "nonce", "exp"]},
            )
            if payload.get("type") != "oidc_state":
                raise OIDCError("Invalid state token type.")
            return payload
        except jwt.ExpiredSignatureError as e:
            raise OIDCError("OIDC login session has expired. Please try again.") from e
        except jwt.InvalidTokenError as e:
            raise OIDCError(f"Invalid state parameter: {e}") from e

    async def exchange_code(
        self,
        token_endpoint: str,
        code: str,
        client_id: str,
        client_secret: Optional[str],
        redirect_uri: str,
    ) -> Dict[str, Any]:
        """Exchanges authorization code for tokens at the token endpoint."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
        }
        if client_secret:
            data["client_secret"] = client_secret

        headers = {"Accept": "application/json"}
        auth = None
        if client_secret:
            auth = (client_id, client_secret)

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(token_endpoint, data=data, auth=auth, headers=headers)
                if resp.status_code != 200:
                    raise OIDCError(f"Token endpoint returned HTTP {resp.status_code}: {resp.text}")
                return resp.json()
            except httpx.HTTPError as e:
                raise OIDCError(f"Token exchange failed: {e}") from e

    async def verify_id_token(
        self,
        id_token: str,
        jwks_uri: str,
        expected_issuer: str,
        expected_client_id: str,
        expected_nonce: str,
        clock_skew_seconds: int = 120,
    ) -> Dict[str, Any]:
        """
        Verifies ID token signature against IdP JWKS, checks issuer, audience,
        nonce, expiration, and clock skew.
        """
        try:
            unverified_header = jwt.get_unverified_header(id_token)
        except Exception as e:
            raise OIDCError(f"Invalid ID token header: {e}") from e

        alg = unverified_header.get("alg", "RS256")
        kid = unverified_header.get("kid")

        jwks_data = await self.get_jwks(jwks_uri)
        keys = jwks_data.get("keys", [])

        matching_key = None
        for k in keys:
            if kid and k.get("kid") == kid:
                matching_key = k
                break
            elif not kid and k.get("kty") == "RSA":
                matching_key = k
                break

        if not matching_key:
            raise OIDCError(f"Unable to find matching public key for kid '{kid}' in JWKS.")

        try:
            public_key = RSAAlgorithm.from_jwk(matching_key)
        except Exception as e:
            raise OIDCError(f"Failed to construct public key from JWK: {e}") from e

        try:
            claims = jwt.decode(
                id_token,
                public_key,
                algorithms=[alg],
                audience=expected_client_id,
                issuer=expected_issuer,
                leeway=clock_skew_seconds,
                options={
                    "require": ["sub", "iss", "aud", "exp"],
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.ExpiredSignatureError as e:
            raise OIDCError("ID token has expired.") from e
        except jwt.InvalidAudienceError as e:
            raise OIDCError(f"ID token audience mismatch: {e}") from e
        except jwt.InvalidIssuerError as e:
            raise OIDCError(f"ID token issuer mismatch: {e}") from e
        except jwt.InvalidSignatureError as e:
            raise OIDCError("ID token signature verification failed.") from e
        except jwt.InvalidTokenError as e:
            raise OIDCError(f"Invalid ID token: {e}") from e

        # Strict Nonce Verification (Replay / Token Injection defense)
        token_nonce = claims.get("nonce")
        if not token_nonce or token_nonce != expected_nonce:
            raise OIDCError("ID token nonce mismatch. Potential token replay or injection.")

        return claims
