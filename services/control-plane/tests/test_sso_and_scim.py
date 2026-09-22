"""
Comprehensive Test Suite for Prompt 18:
- Generic OIDC Discovery & Login
- SAML 2.0 Metadata & ACS Login
- Security Validations: Forged assertions, replay attacks, XML bombs, state/nonce tampering
- Domain Verification & SSO Enforcement
- SCIM 2.0 Users and Groups Directory Sync
- Instant Deprovisioning Cascade & Prompt 20 Owner-Left Hook
- Real-time Group-to-Role Propagation
"""
import base64
import copy
import hashlib
import time
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple, Optional, List
import xml.etree.ElementTree as ET

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import jwt
from jwt.algorithms import RSAAlgorithm
from fastapi.testclient import TestClient

from main import app
from db.session import AsyncSessionLocal
from db.models import (
    Organization, User, OrganizationMember, App, AppShare,
    ConnectorCredential, AuditEvent, SCIMGroup, SCIMGroupRoleMapping,
    OrganizationIdentityProvider, OrganizationVerifiedDomain
)
from db.dal import (
    OrganizationDAL, UserDAL, AppDAL, AppShareDAL, ConnectorCredentialDAL,
    DomainDAL, IdpDAL, SCIMTokenDAL
)
from services.domain_verification import register_test_dns_record, clear_test_dns_records
from api.sso import _oidc_service

client = TestClient(app)


# ==========================================
# Crypto Helpers for Testing Mock IdP
# ==========================================

def _generate_rsa_key_and_cert() -> Tuple[rsa.RSAPrivateKey, str, Dict[str, Any]]:
    """Generates an RSA private key, X.509 certificate PEM, and JWK."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Keycloak Mock IdP")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(private_key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"] = "mock-key-1"
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return private_key, cert_pem, jwk


def _build_signed_saml_response(
    private_key: rsa.RSAPrivateKey,
    issuer_url: str = "https://idp.acme.com",
    sp_entity_id: str = "urn:capsule:sp",
    acs_url: str = "http://localhost:8000/v1/auth/sso/saml/callback",
    email: str = "alice@acme.corp",
    assertion_id: Optional[str] = None,
    not_on_or_after_offset_minutes: int = 10,
    tamper_email_after_sign: Optional[str] = None,
) -> str:
    """Builds a cryptographically signed SAML 2.0 Response XML."""
    a_id = assertion_id or f"_assert_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    issue_instant = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    not_on_or_after = (now + timedelta(minutes=not_on_or_after_offset_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    not_before = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Unsigned Assertion XML
    raw_assertion = (
        f'<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="{a_id}" IssueInstant="{issue_instant}" Version="2.0">'
        f'<saml:Issuer>{issuer_url}</saml:Issuer>'
        f'<saml:Subject>'
        f'<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{email}</saml:NameID>'
        f'<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData NotOnOrAfter="{not_on_or_after}" Recipient="{acs_url}"/>'
        f'</saml:SubjectConfirmation>'
        f'</saml:Subject>'
        f'<saml:Conditions NotBefore="{not_before}" NotOnOrAfter="{not_on_or_after}">'
        f'<saml:AudienceRestriction>'
        f'<saml:Audience>{sp_entity_id}</saml:Audience>'
        f'</saml:AudienceRestriction>'
        f'</saml:Conditions>'
        f'<saml:AttributeStatement>'
        f'<saml:Attribute Name="email"><saml:AttributeValue>{email}</saml:AttributeValue></saml:Attribute>'
        f'<saml:Attribute Name="displayName"><saml:AttributeValue>{email.split("@")[0].title()}</saml:AttributeValue></saml:Attribute>'
        f'</saml:AttributeStatement>'
        f'</saml:Assertion>'
    )

    c14n_assertion = ET.canonicalize(raw_assertion)
    digest = hashlib.sha256(c14n_assertion.encode("utf-8")).digest()
    digest_b64 = base64.b64encode(digest).decode("utf-8")

    signed_info_xml = (
        f'<ds:SignedInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
        f'<ds:CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"/>'
        f'<ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"/>'
        f'<ds:Reference URI="#{a_id}">'
        f'<ds:Transforms>'
        f'<ds:Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>'
        f'<ds:Transform Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"/>'
        f'</ds:Transforms>'
        f'<ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>'
        f'<ds:DigestValue>{digest_b64}</ds:DigestValue>'
        f'</ds:Reference>'
        f'</ds:SignedInfo>'
    )

    c14n_signed_info = ET.canonicalize(signed_info_xml).encode("utf-8")
    signature = private_key.sign(c14n_signed_info, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.b64encode(signature).decode("utf-8")

    sig_xml = f'<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{signed_info_xml}<ds:SignatureValue>{sig_b64}</ds:SignatureValue></ds:Signature>'

    # If tampering is requested (forged assertion test), replace email in assertion body AFTER signing!
    actual_email = tamper_email_after_sign or email

    signed_assertion = (
        f'<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="{a_id}" IssueInstant="{issue_instant}" Version="2.0">'
        f'<saml:Issuer>{issuer_url}</saml:Issuer>'
        f'{sig_xml}'
        f'<saml:Subject>'
        f'<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{actual_email}</saml:NameID>'
        f'<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData NotOnOrAfter="{not_on_or_after}" Recipient="{acs_url}"/>'
        f'</saml:SubjectConfirmation>'
        f'</saml:Subject>'
        f'<saml:Conditions NotBefore="{not_before}" NotOnOrAfter="{not_on_or_after}">'
        f'<saml:AudienceRestriction>'
        f'<saml:Audience>{sp_entity_id}</saml:Audience>'
        f'</saml:AudienceRestriction>'
        f'</saml:Conditions>'
        f'<saml:AttributeStatement>'
        f'<saml:Attribute Name="email"><saml:AttributeValue>{actual_email}</saml:AttributeValue></saml:Attribute>'
        f'<saml:Attribute Name="displayName"><saml:AttributeValue>{actual_email.split("@")[0].title()}</saml:AttributeValue></saml:Attribute>'
        f'</saml:AttributeStatement>'
        f'</saml:Assertion>'
    )

    response_xml = (
        f'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" ID="_resp_{uuid.uuid4().hex}" Version="2.0">'
        f'<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
        f'{signed_assertion}'
        f'</samlp:Response>'
    )

    return base64.b64encode(response_xml.encode("utf-8")).decode("utf-8")


def _get_admin_headers() -> Dict[str, str]:
    """Generates standard Bearer token for organization owner (Alice)."""
    return {"Authorization": "Bearer mock-alice-token"}


# ==========================================
# Test Cases
# ==========================================

@pytest.mark.asyncio
async def test_domain_verification_lifecycle():
    """Verify domain claim creation, DNS TXT challenge check, and collision protection."""
    clear_test_dns_records()
    headers = _get_admin_headers()

    # Get org
    async with AsyncSessionLocal() as session:
        org_dal = OrganizationDAL(session)
        org = await org_dal.get_by_slug("acme-corp")
        org_id = org.id

    test_domain = f"test-{uuid.uuid4().hex[:6]}.corp"

    # 1. Claim domain
    res = client.post(f"/v1/organizations/{org_id}/domains", json={"domain": test_domain}, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "pending"
    token = data["verification_token"]
    assert token.startswith("capsule-domain-verification=")

    # 2. Verify without DNS record -> should fail
    verify_res = client.post(f"/v1/organizations/{org_id}/domains/{test_domain}/verify", headers=headers)
    assert verify_res.status_code == 400
    assert verify_res.json()["detail"]["code"] == "VERIFICATION_FAILED"

    # 3. Place DNS TXT record in mock registry
    register_test_dns_record(f"_capsule-challenge.{test_domain}", [token])

    # 4. Verify now -> should succeed
    verify_res = client.post(f"/v1/organizations/{org_id}/domains/{test_domain}/verify", headers=headers)
    assert verify_res.status_code == 200
    assert verify_res.json()["status"] == "verified"
    assert verify_res.json()["verified_at"] is not None

    # 5. Collision protection: another org cannot claim verified domain
    async with AsyncSessionLocal() as session:
        org_dal = OrganizationDAL(session)
        other_org = await org_dal.create(slug=f"other-{uuid.uuid4().hex[:6]}", name="Other Corp")
        await session.commit()
        other_org_id = other_org.id

    collision_res = client.post(
        f"/v1/organizations/{other_org_id}/domains",
        json={"domain": test_domain},
        headers=_get_admin_headers(),
    )
    # Different org claiming same domain should receive 409 Conflict
    assert collision_res.status_code in [403, 409]


@pytest.mark.asyncio
async def test_oidc_discovery_and_successful_login(monkeypatch):
    """Simulates Keycloak OIDC login with discovery, JWKS verification, and JIT provisioning."""
    key, cert_pem, jwk = _generate_rsa_key_and_cert()
    headers = _get_admin_headers()

    async with AsyncSessionLocal() as session:
        org_dal = OrganizationDAL(session)
        org = await org_dal.get_by_slug("acme-corp")
        org_id = org.id

    discovery_url = "https://keycloak.mock/auth/realms/acme/.well-known/openid-configuration"
    jwks_uri = "https://keycloak.mock/auth/realms/acme/protocol/openid-connect/certs"
    token_endpoint = "https://keycloak.mock/auth/realms/acme/protocol/openid-connect/token"
    issuer_url = "https://keycloak.mock/auth/realms/acme"
    client_id = "capsule-platform-client"

    # Mock discovery doc
    mock_discovery = {
        "issuer": issuer_url,
        "authorization_endpoint": "https://keycloak.mock/auth/realms/acme/protocol/openid-connect/auth",
        "token_endpoint": token_endpoint,
        "jwks_uri": jwks_uri,
    }

    # Mock JWKS response
    mock_jwks = {"keys": [jwk]}

    # Monkeypatch OIDC discovery & JWKS calls
    async def mock_discover(url):
        return mock_discovery

    async def mock_get_jwks(url):
        return mock_jwks

    monkeypatch.setattr(_oidc_service, "discover", mock_discover)
    monkeypatch.setattr(_oidc_service, "get_jwks", mock_get_jwks)

    # 1. Configure OIDC IdP for org
    put_res = client.put(
        f"/v1/organizations/{org_id}/sso/idp",
        json={
            "provider_type": "oidc",
            "is_active": True,
            "session_lifetime_seconds": 14400,
            "oidc_issuer_url": issuer_url,
            "oidc_client_id": client_id,
            "oidc_client_secret": "mock-client-secret-123",
            "oidc_discovery_url": discovery_url,
        },
        headers=headers,
    )
    assert put_res.status_code == 200

    # 2. Dispatch login -> /v1/auth/sso/login
    login_res = client.get(
        "/v1/auth/sso/login?org_slug=acme-corp&target_app=leave-tracker&return_to=/dashboard",
        follow_redirects=False,
    )
    assert login_res.status_code == 302
    redirect_loc = login_res.headers["Location"]
    assert "https://keycloak.mock/auth/realms/acme" in redirect_loc

    # Extract state and nonce from redirect URL
    import urllib.parse
    parsed_url = urllib.parse.urlparse(redirect_loc)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    state = query_params["state"][0]
    nonce = query_params["nonce"][0]

    # 3. Mock code exchange returning valid ID token
    now_int = int(time.time())
    id_token_payload = {
        "iss": issuer_url,
        "sub": "keycloak-usr-1001",
        "aud": client_id,
        "email": "keycloak.user@acme.com",
        "name": "Keycloak User",
        "nonce": nonce,
        "iat": now_int,
        "exp": now_int + 3600,
    }
    id_token = jwt.encode(id_token_payload, key, algorithm="RS256", headers={"kid": "mock-key-1"})

    async def mock_exchange_code(token_endpoint, code, client_id, client_secret, redirect_uri):
        return {"id_token": id_token, "access_token": "mock-access-token"}

    monkeypatch.setattr(_oidc_service, "exchange_code", mock_exchange_code)

    # 4. Callback to /v1/auth/sso/oidc/callback
    cb_res = client.get(
        f"/v1/auth/sso/oidc/callback?code=mock-auth-code&state={state}",
        follow_redirects=False,
    )
    assert cb_res.status_code == 302
    target_callback = cb_res.headers["Location"]
    assert "leave-tracker.apps.localhost" in target_callback
    assert "ticket=" in target_callback

    # Verify user was JIT created in database
    async with AsyncSessionLocal() as session:
        user_dal = UserDAL(session)
        created_user = await user_dal.get_by_email("keycloak.user@acme.com")
        assert created_user is not None
        assert created_user.status == "active"
        assert created_user.identity_subject == "keycloak-usr-1001"


@pytest.mark.asyncio
async def test_oidc_security_validations(monkeypatch):
    """Validates state tampering, nonce mismatch, and signature forgery rejection."""
    key, cert_pem, jwk = _generate_rsa_key_and_cert()
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # 1. Tampered state
    res = client.get("/v1/auth/sso/oidc/callback?code=abc&state=tampered.state.jwt")
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_STATE"

    # 2. Nonce Mismatch & Forged Signature
    mock_jwks = {"keys": [jwk]}
    async def mock_get_jwks(url):
        return mock_jwks
    monkeypatch.setattr(_oidc_service, "get_jwks", mock_get_jwks)

    # Nonce mismatch test
    now_int = int(time.time())
    bad_nonce_token = jwt.encode(
        {"iss": "https://idp.com", "sub": "u1", "aud": "c1", "nonce": "wrong_nonce", "exp": now_int + 3600},
        key, algorithm="RS256", headers={"kid": "mock-key-1"}
    )
    with pytest.raises(Exception) as exc_info:
        await _oidc_service.verify_id_token(bad_nonce_token, "http://jwks", "https://idp.com", "c1", expected_nonce="expected_nonce")
    assert "nonce mismatch" in str(exc_info.value).lower()

    # Forged signature test (signed with wrong_key)
    forged_token = jwt.encode(
        {"iss": "https://idp.com", "sub": "u1", "aud": "c1", "nonce": "n1", "exp": now_int + 3600},
        wrong_key, algorithm="RS256", headers={"kid": "mock-key-1"}
    )
    with pytest.raises(Exception) as exc_info:
        await _oidc_service.verify_id_token(forged_token, "http://jwks", "https://idp.com", "c1", expected_nonce="n1")
    assert "signature verification failed" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_saml_successful_login_and_metadata():
    """Generates valid signed SAML Response, performs ACS handshake, verifies JIT provisioning."""
    key, cert_pem, _ = _generate_rsa_key_and_cert()
    headers = _get_admin_headers()

    async with AsyncSessionLocal() as session:
        org_dal = OrganizationDAL(session)
        org = await org_dal.get_by_slug("acme-corp")
        org_id = org.id

    # 1. Verify SP Metadata endpoint
    meta_res = client.get("/v1/auth/sso/saml/metadata")
    assert meta_res.status_code == 200
    assert "EntityDescriptor" in meta_res.text
    assert "AssertionConsumerService" in meta_res.text

    # 2. Configure SAML IdP
    put_res = client.put(
        f"/v1/organizations/{org_id}/sso/idp",
        json={
            "provider_type": "saml",
            "is_active": True,
            "session_lifetime_seconds": 18000,
            "saml_entity_id": "https://saml-idp.example.com",
            "saml_sso_url": "https://saml-idp.example.com/sso",
            "saml_x509_cert": cert_pem,
            "saml_sp_entity_id": "urn:capsule:sp",
            "saml_acs_url": "http://localhost:8000/v1/auth/sso/saml/callback",
        },
        headers=headers,
    )
    assert put_res.status_code == 200

    # 3. Build valid signed SAML Response for a new user
    saml_user_email = f"saml.user.{uuid.uuid4().hex[:4]}@acme.corp"
    saml_response_b64 = _build_signed_saml_response(
        private_key=key,
        issuer_url="https://saml-idp.example.com",
        email=saml_user_email,
    )

    # Encode RelayState with org_id
    relay_payload = {
        "org_id": str(org_id),
        "target_app": "leave-tracker",
        "return_to": "/",
    }
    relay_state = jwt.encode(relay_payload, "control-plane-dev-jwt-secret-do-not-use-in-prod", algorithm="HS256")

    # 4. POST to SAML ACS
    acs_res = client.post(
        "/v1/auth/sso/saml/callback",
        data={"SAMLResponse": saml_response_b64, "RelayState": relay_state},
        follow_redirects=False,
    )
    assert acs_res.status_code == 302
    assert "leave-tracker.apps.localhost" in acs_res.headers["Location"]

    # Verify user JIT provisioning
    async with AsyncSessionLocal() as session:
        user_dal = UserDAL(session)
        saml_user = await user_dal.get_by_email(saml_user_email)
        assert saml_user is not None
        assert saml_user.status == "active"


@pytest.mark.asyncio
async def test_saml_security_rejections():
    """
    Blocks:
    1. Forged assertions (tampered XML payload)
    2. Replayed assertions (Assertion ID reuse)
    3. Audience mismatches
    4. Clock skew violations
    5. XML entity expansion / XXE bombs
    """
    key, cert_pem, _ = _generate_rsa_key_and_cert()

    async with AsyncSessionLocal() as session:
        org_dal = OrganizationDAL(session)
        org = await org_dal.get_by_slug("acme-corp")
        org_id = org.id
        idp_dal = IdpDAL(session)
        await idp_dal.upsert_idp(
            org_id=org_id,
            provider_type="saml",
            is_active=True,
            saml_entity_id="https://saml-idp.example.com",
            saml_sso_url="https://saml-idp.example.com/sso",
            saml_x509_cert=cert_pem,
            saml_sp_entity_id="urn:capsule:sp",
            saml_acs_url="http://localhost:8000/v1/auth/sso/saml/callback",
        )
        await session.commit()

    relay_payload = {"org_id": str(org_id), "target_app": "leave-tracker", "return_to": "/"}
    relay_state = jwt.encode(relay_payload, "control-plane-dev-jwt-secret-do-not-use-in-prod", algorithm="HS256")

    # 1. Forged assertion: tamper email AFTER computing cryptographic signature
    forged_b64 = _build_signed_saml_response(
        private_key=key,
        email="original@acme.corp",
        tamper_email_after_sign="attacker@acme.corp",
    )
    res_forged = client.post(
        "/v1/auth/sso/saml/callback",
        data={"SAMLResponse": forged_b64, "RelayState": relay_state},
    )
    assert res_forged.status_code == 401
    assert "digest verification failed" in res_forged.json()["detail"]["message"]

    # 2. Replayed assertion: reuse same Assertion ID
    replay_assertion_id = f"_replay_id_{uuid.uuid4().hex}"
    valid_b64 = _build_signed_saml_response(
        private_key=key,
        assertion_id=replay_assertion_id,
        email="replay.test@acme.corp",
    )
    # First time -> 302 Success
    res1 = client.post(
        "/v1/auth/sso/saml/callback",
        data={"SAMLResponse": valid_b64, "RelayState": relay_state},
        follow_redirects=False,
    )
    assert res1.status_code == 302

    # Second time with EXACT same Assertion ID -> 401 REPLAY_ATTACK_DETECTED
    res2 = client.post(
        "/v1/auth/sso/saml/callback",
        data={"SAMLResponse": valid_b64, "RelayState": relay_state},
    )
    assert res2.status_code == 401
    assert res2.json()["detail"]["code"] == "REPLAY_ATTACK_DETECTED"

    # 3. Audience mismatch
    mismatch_aud_b64 = _build_signed_saml_response(
        private_key=key,
        sp_entity_id="urn:unauthorized:sp",
        email="aud.mismatch@acme.corp",
    )
    res_aud = client.post(
        "/v1/auth/sso/saml/callback",
        data={"SAMLResponse": mismatch_aud_b64, "RelayState": relay_state},
    )
    assert res_aud.status_code == 401
    assert "audience mismatch" in res_aud.json()["detail"]["message"].lower()

    # 4. Clock-skew violation (NotOnOrAfter expired 15 minutes ago)
    expired_b64 = _build_signed_saml_response(
        private_key=key,
        not_on_or_after_offset_minutes=-15,
        email="expired@acme.corp",
    )
    res_exp = client.post(
        "/v1/auth/sso/saml/callback",
        data={"SAMLResponse": expired_b64, "RelayState": relay_state},
    )
    assert res_exp.status_code == 401
    assert "expired" in res_exp.json()["detail"]["message"].lower()

    # 5. XML bomb / XXE Attack
    xml_bomb = """<?xml version="1.0"?>
    <!DOCTYPE lolz [
      <!ENTITY lol "lol">
      <!ELEMENT lolz (#PCDATA)>
      <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
    ]>
    <samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol">&lol1;</samlp:Response>"""
    bomb_b64 = base64.b64encode(xml_bomb.encode("utf-8")).decode("utf-8")
    res_bomb = client.post(
        "/v1/auth/sso/saml/callback",
        data={"SAMLResponse": bomb_b64, "RelayState": relay_state},
    )
    assert res_bomb.status_code in [400, 401]


@pytest.mark.asyncio
async def test_sso_enforcement_blocks_dev_passwords():
    """When an organization enforces SSO for a verified domain, local dev tickets are blocked."""
    headers = _get_admin_headers()
    async with AsyncSessionLocal() as session:
        org_dal = OrganizationDAL(session)
        org = await org_dal.get_by_slug("acme-corp")
        org_id = org.id

    enforced_domain = f"enforce-{uuid.uuid4().hex[:6]}.com"

    # Claim & verify domain
    client.post(f"/v1/organizations/{org_id}/domains", json={"domain": enforced_domain}, headers=headers)
    register_test_dns_record(f"_capsule-challenge.{enforced_domain}", ["capsule-domain-verification=mock"])
    async with AsyncSessionLocal() as session:
        dom_dal = DomainDAL(session)
        await dom_dal.mark_verified(enforced_domain)
        await session.commit()

    # Enable enforce_sso on IdP
    idp_res = client.put(
        f"/v1/organizations/{org_id}/sso/idp",
        json={
            "provider_type": "oidc",
            "is_active": True,
            "enforce_sso": True,
            "oidc_issuer_url": "https://idp.example.com",
            "oidc_client_id": "client-123",
        },
        headers=headers,
    )
    assert idp_res.status_code == 200

    # User with @enforced_domain trying to authenticate with mock issuer
    mock_token = jwt.encode(
        {
            "sub": "usr_sso_block_test",
            "email": f"worker@{enforced_domain}",
            "org_slug": "acme-corp",
            "iss": "mock",
            "exp": int(time.time()) + 3600,
        },
        "control-plane-dev-jwt-secret-do-not-use-in-prod",
        algorithm="HS256",
    )

    # Calling /v1/auth/me with mock token should be blocked with 403 SSO_REQUIRED
    res = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {mock_token}"})
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "SSO_REQUIRED"

    # Reset enforce_sso so other tests aren't affected
    async with AsyncSessionLocal() as session:
        idp_dal = IdpDAL(session)
        await idp_dal.upsert_idp(org_id=org_id, provider_type="oidc", enforce_sso=False)
        await session.commit()


@pytest.mark.asyncio
async def test_scim_token_rotation_and_auth():
    """SCIM 2.0 token rotation, invalidation of old tokens, and bearer auth verification."""
    headers = _get_admin_headers()
    async with AsyncSessionLocal() as session:
        org_dal = OrganizationDAL(session)
        org = await org_dal.get_by_slug("acme-corp")
        org_id = org.id

    # 1. Rotate token
    rotate_res = client.post(f"/v1/organizations/{org_id}/scim/rotate-token", headers=headers)
    assert rotate_res.status_code == 200
    token1 = rotate_res.json()["token"]

    # 2. Query /scim/v2/Users with token1 -> should succeed
    scim_headers1 = {"Authorization": f"Bearer {token1}"}
    users_res1 = client.get("/scim/v2/Users", headers=scim_headers1)
    assert users_res1.status_code == 200
    assert users_res1.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]

    # 3. Rotate token again -> token1 is revoked, token2 issued
    rotate_res2 = client.post(f"/v1/organizations/{org_id}/scim/rotate-token", headers=headers)
    token2 = rotate_res2.json()["token"]

    # 4. Old token1 now rejected with 401
    users_res_old = client.get("/scim/v2/Users", headers=scim_headers1)
    assert users_res_old.status_code == 401

    # 5. New token2 succeeds
    scim_headers2 = {"Authorization": f"Bearer {token2}"}
    users_res2 = client.get("/scim/v2/Users", headers=scim_headers2)
    assert users_res2.status_code == 200


@pytest.mark.asyncio
async def test_scim_deprovisioning_cascade_and_owner_left_hook():
    """
    SCIM deprovisioning (active: false):
    1. Sets user status to 'deprovisioned'
    2. Revokes sessions & publish tokens immediately
    3. Wipes all connector credentials
    4. Revokes application shares
    5. Prompt 20 Hook: Suspends apps owned by deprovisioned user (FR-034) with audit log
    """
    headers = _get_admin_headers()
    async with AsyncSessionLocal() as session:
        org_dal = OrganizationDAL(session)
        org = await org_dal.get_by_slug("acme-corp")
        org.environment_profile = {**(org.environment_profile or {}), "owner_left_policy": "suspend"}
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(org, "environment_profile")
        org_id = org.id
        token_dal = SCIMTokenDAL(session)
        scim_token, _ = await token_dal.rotate_token(org_id)
        await session.commit()

    scim_headers = {"Authorization": f"Bearer {scim_token}"}

    # 1. Provision user via SCIM
    test_email = f"deprovision.target.{uuid.uuid4().hex[:6]}@acme.corp"
    user_res = client.post(
        "/scim/v2/Users",
        json={"userName": test_email, "displayName": "Deprovision Target", "active": True},
        headers=scim_headers,
    )
    assert user_res.status_code == 201
    user_id = uuid.UUID(user_res.json()["id"])

    # 2. Attach a connector credential and create an app owned by this user
    async with AsyncSessionLocal() as session:
        cred_dal = ConnectorCredentialDAL(session)
        await cred_dal.set_credential(
            organization_id=org_id,
            connector_name="sheets.read",
            identity_type="viewer",
            credential_data={"token": "ya29.secret_token_123"},
            user_id=user_id,
        )

        app_dal = AppDAL(session)
        test_app = await app_dal.create(
            app_key=f"app-{uuid.uuid4().hex[:6]}",
            name="Orphan Target App",
            organization_id=org_id,
            owner_user_id=user_id,
            status="active",
        )

        share_dal = AppShareDAL(session)
        await share_dal.create_share(
            app_id=test_app.id,
            user_id=user_id,
            app_role="editor",
            status="active",
        )
        await session.commit()
        test_app_id = test_app.id

    # 3. Trigger Deprovisioning via SCIM PATCH active: false
    patch_res = client.patch(
        f"/scim/v2/Users/{user_id}",
        json={"Operations": [{"op": "replace", "path": "active", "value": False}]},
        headers=scim_headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["active"] is False

    # 4. Verify the cascade in Database
    async with AsyncSessionLocal() as session:
        # A. User status and revocation timestamps
        user_dal = UserDAL(session)
        user = await user_dal.get_by_id(user_id)
        assert user.status == "deprovisioned"
        assert user.sessions_revoked_at is not None
        assert user.tokens_revoked_at is not None

        # B. Connector credentials must be wiped (count == 0)
        cred_dal = ConnectorCredentialDAL(session)
        creds = await cred_dal.get_credential(org_id, "sheets.read", identity_type="viewer", user_id=user_id)
        assert creds is None

        # C. App shares must be revoked
        share_dal = AppShareDAL(session)
        active_shares = await share_dal.find_active_shares_for_user(test_app_id, user_id)
        assert len(active_shares) == 0

        # D. Prompt 20 Owner-Left Hook: App must be suspended (FR-034)
        app_dal = AppDAL(session)
        app_record = await app_dal.get_by_id(test_app_id)
        assert app_record.status == "suspended"
        assert "prevent unmanaged operation (FR-034)" in app_record.suspension_reason

        # E. Audit event recorded
        from sqlalchemy import select
        audit_res = await session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "app.owner_deprovisioned",
                AuditEvent.target_id == test_app_id,
            )
        )
        audit_event = audit_res.scalar_one_or_none()
        assert audit_event is not None
        assert audit_event.metadata_["owner_email"] == test_email


@pytest.mark.asyncio
async def test_scim_groups_and_realtime_role_propagation():
    """
    SCIM directory groups sync and propagate application roles within seconds.
    Adding a user to a mapped group grants the AppShare; removing revokes it.
    """
    headers = _get_admin_headers()
    async with AsyncSessionLocal() as session:
        org_dal = OrganizationDAL(session)
        org = await org_dal.get_by_slug("acme-corp")
        org_id = org.id
        app_dal = AppDAL(session)
        user_dal = UserDAL(session)
        alice = await user_dal.get_by_email("alice@example.com")
        leave_app = await app_dal.get_by_key(org_id, "leave-tracker")
        if not leave_app:
            leave_app = await app_dal.create(
                app_key="leave-tracker",
                name="Leave Tracker",
                organization_id=org_id,
                owner_user_id=alice.id if alice else None,
                status="active",
            )
            await session.commit()
        app_id = leave_app.id

        token_dal = SCIMTokenDAL(session)
        scim_token, _ = await token_dal.rotate_token(org_id)
        await session.commit()

    scim_headers = {"Authorization": f"Bearer {scim_token}"}

    # 1. Create a user via SCIM
    member_email = f"group.member.{uuid.uuid4().hex[:6]}@acme.corp"
    user_res = client.post(
        "/scim/v2/Users",
        json={"userName": member_email, "displayName": "Group Member", "active": True},
        headers=scim_headers,
    )
    user_id = user_res.json()["id"]

    # 2. Create a SCIM group
    group_name = f"Engineering-{uuid.uuid4().hex[:4]}"
    group_res = client.post(
        "/scim/v2/Groups",
        json={"displayName": group_name},
        headers=scim_headers,
    )
    assert group_res.status_code == 201
    group_id = group_res.json()["id"]

    # 3. Create Group-to-Role mapping in dashboard: Engineering -> leave-tracker with role 'editor'
    map_res = client.post(
        f"/v1/organizations/{org_id}/group-role-mappings",
        json={"group_id": group_id, "app_id": str(app_id), "app_role": "editor"},
        headers=headers,
    )
    assert map_res.status_code == 201

    # 4. Add user to SCIM group via PATCH
    patch_group_res = client.patch(
        f"/scim/v2/Groups/{group_id}",
        json={"Operations": [{"op": "add", "path": "members", "value": [{"value": user_id}]}]},
        headers=scim_headers,
    )
    assert patch_group_res.status_code == 200

    # 5. Verify that AppShare was immediately created!
    async with AsyncSessionLocal() as session:
        share_dal = AppShareDAL(session)
        active_shares = await share_dal.find_active_shares_for_user(app_id, uuid.UUID(user_id))
        assert len(active_shares) == 1
        assert active_shares[0].app_role == "editor"
        assert active_shares[0].metadata_["source"] == "scim_group"

    # 6. Remove user from SCIM group via PATCH
    remove_group_res = client.patch(
        f"/scim/v2/Groups/{group_id}",
        json={"Operations": [{"op": "remove", "path": f"members[value eq \"{user_id}\"]"}]},
        headers=scim_headers,
    )
    assert remove_group_res.status_code == 200

    # 7. Verify that AppShare was immediately revoked!
    async with AsyncSessionLocal() as session:
        share_dal = AppShareDAL(session)
        active_shares = await share_dal.find_active_shares_for_user(app_id, uuid.UUID(user_id))
        assert len(active_shares) == 0
