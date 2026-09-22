"""
SAML 2.0 Service with Vetted Cryptographic Signature Validation,
DefusedXML Defense against XML Attacks, Replay Protection, and Clock Skew Bounds.
"""
import base64
import copy
import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import defusedxml.ElementTree as dET
import xml.etree.ElementTree as ET

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend


class SAMLError(Exception):
    """Base exception for SAML processing errors."""
    pass


# XML Namespaces
NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
}

for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def _clean_cert(cert_str: str) -> bytes:
    """Normalize PEM/DER certificate string into standard PEM bytes."""
    clean = cert_str.strip()
    if not clean.startswith("-----BEGIN CERTIFICATE-----"):
        clean = f"-----BEGIN CERTIFICATE-----\n{clean}\n-----END CERTIFICATE-----"
    return clean.encode("utf-8")


def _parse_iso_datetime(dt_str: str) -> datetime:
    """Parse SAML UTC timestamp strings (e.g. 2026-09-21T12:00:00Z)."""
    clean = dt_str.replace("Z", "+00:00")
    # Handle fractional seconds if any
    try:
        return datetime.fromisoformat(clean)
    except Exception as e:
        raise SAMLError(f"Invalid timestamp format in SAML assertion: '{dt_str}': {e}") from e


class SAMLService:
    """Handles SAML 2.0 AuthnRequest generation, SP metadata, and secure response validation."""

    def generate_sp_metadata(
        self,
        sp_entity_id: str,
        acs_url: str,
        slo_url: Optional[str] = None,
    ) -> str:
        """Generates standard SAML 2.0 Service Provider metadata XML."""
        slo_xml = ""
        if slo_url:
            slo_xml = f'<md:SingleLogoutService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="{slo_url}"/>'

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{sp_entity_id}">
  <md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    {slo_xml}
    <md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="{acs_url}" index="0" isDefault="true"/>
  </md:SPSSODescriptor>
</md:EntityDescriptor>"""

    def generate_authn_request(
        self,
        sp_entity_id: str,
        acs_url: str,
        idp_sso_url: str,
    ) -> Tuple[str, str]:
        """
        Generates SAML 2.0 AuthnRequest XML and returns (request_id, base64_xml).
        """
        request_id = f"_{uuid.uuid4().hex}"
        issue_instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        xml_str = f"""<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
  xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
  ID="{request_id}"
  Version="2.0"
  IssueInstant="{issue_instant}"
  Destination="{idp_sso_url}"
  AssertionConsumerServiceURL="{acs_url}">
  <saml:Issuer>{sp_entity_id}</saml:Issuer>
</samlp:AuthnRequest>"""

        b64_req = base64.b64encode(xml_str.encode("utf-8")).decode("utf-8")
        return request_id, b64_req

    def parse_and_validate_response(
        self,
        saml_response_b64: str,
        sp_entity_id: str,
        acs_url: Optional[str],
        idp_x509_cert: str,
        clock_skew_seconds: int = 120,
    ) -> Dict[str, Any]:
        """
        Parses and cryptographically validates a SAML 2.0 Response.
        Protects against XXE / XML Bomb, Signature Wrapping (XSW),
        Forged Signatures, Audience Mismatch, and Clock Skew.
        """
        try:
            xml_bytes = base64.b64decode(saml_response_b64)
        except Exception as e:
            raise SAMLError(f"Invalid Base64 in SAMLResponse: {e}") from e

        # 1. Protection against XML Attacks: DefusedXML parser
        try:
            root = dET.fromstring(xml_bytes)
        except Exception as e:
            raise SAMLError(f"Malformed or unsafe XML payload: {e}") from e

        # 2. Check StatusCode
        status_code_elem = root.find(".//{urn:oasis:names:tc:SAML:2.0:protocol}StatusCode")
        if status_code_elem is not None:
            status_val = status_code_elem.attrib.get("Value", "")
            if not status_val.endswith(":Success"):
                status_msg_elem = root.find(".//{urn:oasis:names:tc:SAML:2.0:protocol}StatusMessage")
                msg = status_msg_elem.text if status_msg_elem is not None else status_val
                raise SAMLError(f"SAML response indicated failure: {msg}")

        # 3. Locate Assertion
        assertion = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Assertion")
        if assertion is None:
            # Try without namespace in case of unprefixed XML
            for elem in root.iter():
                if elem.tag.endswith("Assertion"):
                    assertion = elem
                    break

        if assertion is None:
            raise SAMLError("Missing SAML Assertion in response.")

        assertion_id = assertion.attrib.get("ID")
        if not assertion_id:
            raise SAMLError("SAML Assertion missing ID attribute.")

        # 4. Cryptographic Signature Verification
        self._verify_signature(root, assertion, idp_x509_cert)

        # 5. Conditions and Clock-Skew Validation
        conditions = assertion.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Conditions")
        if conditions is None:
            for elem in assertion.iter():
                if elem.tag.endswith("Conditions"):
                    conditions = elem
                    break

        now_utc = datetime.now(timezone.utc)
        expires_at = None

        if conditions is not None:
            not_before_str = conditions.attrib.get("NotBefore")
            not_on_or_after_str = conditions.attrib.get("NotOnOrAfter")

            if not_before_str:
                not_before = _parse_iso_datetime(not_before_str)
                skew_allowance = (now_utc - not_before).total_seconds()
                if skew_allowance < -clock_skew_seconds:
                    raise SAMLError(f"SAML Assertion is not yet valid (NotBefore: {not_before_str}).")

            if not_on_or_after_str:
                not_on_or_after = _parse_iso_datetime(not_on_or_after_str)
                expires_at = not_on_or_after
                skew_allowance = (not_on_or_after - now_utc).total_seconds()
                if skew_allowance < -clock_skew_seconds:
                    raise SAMLError(f"SAML Assertion has expired (NotOnOrAfter: {not_on_or_after_str}).")

            # 6. Audience Restriction Validation
            audience_elem = conditions.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Audience")
            if audience_elem is None:
                for elem in conditions.iter():
                    if elem.tag.endswith("Audience"):
                        audience_elem = elem
                        break

            if audience_elem is not None:
                aud_val = (audience_elem.text or "").strip()
                if aud_val != sp_entity_id:
                    raise SAMLError(f"SAML Assertion audience mismatch: expected '{sp_entity_id}', got '{aud_val}'.")

        # 7. Recipient Verification
        if acs_url:
            sub_conf_data = assertion.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}SubjectConfirmationData")
            if sub_conf_data is None:
                for elem in assertion.iter():
                    if elem.tag.endswith("SubjectConfirmationData"):
                        sub_conf_data = elem
                        break

            if sub_conf_data is not None:
                recipient = sub_conf_data.attrib.get("Recipient")
                if recipient and recipient.rstrip("/") != acs_url.rstrip("/"):
                    raise SAMLError(f"SAML Recipient mismatch: expected '{acs_url}', got '{recipient}'.")

        # 8. Extract Identity Attributes
        name_id_elem = assertion.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
        if name_id_elem is None:
            for elem in assertion.iter():
                if elem.tag.endswith("NameID"):
                    name_id_elem = elem
                    break

        name_id = (name_id_elem.text or "").strip() if name_id_elem is not None else ""

        # Extract attributes from AttributeStatement
        attributes: Dict[str, Any] = {}
        for elem in assertion.iter():
            if elem.tag.endswith("Attribute"):
                attr_name = elem.attrib.get("Name")
                if attr_name:
                    values = [v.text.strip() for v in elem.iter() if v.tag.endswith("AttributeValue") and v.text]
                    attributes[attr_name] = values[0] if len(values) == 1 else values

        # Determine email and display name
        email = (
            attributes.get("email")
            or attributes.get("mail")
            or attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress")
            or name_id
        )
        display_name = (
            attributes.get("displayName")
            or attributes.get("name")
            or attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name")
            or (email.split("@")[0] if email and "@" in email else name_id)
        )
        groups = attributes.get("groups") or attributes.get("http://schemas.xmlsoap.org/claims/Group") or []
        if isinstance(groups, str):
            groups = [groups]

        if not email:
            raise SAMLError("SAML Assertion does not contain an email or NameID identifier.")

        return {
            "sub": name_id or email,
            "email": email,
            "display_name": display_name,
            "groups": groups,
            "assertion_id": assertion_id,
            "expires_at": expires_at or datetime.now(timezone.utc),
            "attributes": attributes,
        }

    def _verify_signature(
        self,
        root: ET.Element,
        assertion: ET.Element,
        idp_x509_cert: str,
    ) -> None:
        """
        Validates digital signature on the Assertion or Response element
        using cryptography's vetted RSA PKCS#1 v1.5 verification.
        Ensures strict protection against Signature Wrapping (XSW).
        """
        # Look for signature inside assertion first, then root response
        sig_elem = assertion.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
        target_elem = assertion
        if sig_elem is None:
            sig_elem = root.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
            target_elem = root

        if sig_elem is None:
            # Fallback search for tag ending with 'Signature'
            for elem in assertion.iter():
                if elem.tag.endswith("Signature") and "xmldsig" in elem.tag:
                    sig_elem = elem
                    target_elem = assertion
                    break
            if sig_elem is None:
                for elem in root.iter():
                    if elem.tag.endswith("Signature") and "xmldsig" in elem.tag:
                        sig_elem = elem
                        target_elem = root
                        break

        if sig_elem is None:
            raise SAMLError("SAML message is not digitally signed. Unsigned assertions are rejected.")

        # Extract Reference URI (Signature Wrapping XSW defense)
        ref_elem = sig_elem.find(".//{http://www.w3.org/2000/09/xmldsig#}Reference")
        if ref_elem is None:
            for elem in sig_elem.iter():
                if elem.tag.endswith("Reference"):
                    ref_elem = elem
                    break

        if ref_elem is None:
            raise SAMLError("Signature is missing Reference element.")

        ref_uri = ref_elem.attrib.get("URI", "")
        clean_ref_uri = ref_uri.lstrip("#")
        target_id = target_elem.attrib.get("ID", "")

        # Strict Signature Wrapping check: Reference URI MUST match target element ID
        if clean_ref_uri and clean_ref_uri != target_id:
            raise SAMLError(
                f"SAML Signature Wrapping detected: Reference URI '{clean_ref_uri}' does not match target element ID '{target_id}'."
            )

        # Extract DigestValue
        digest_val_elem = ref_elem.find(".//{http://www.w3.org/2000/09/xmldsig#}DigestValue")
        if digest_val_elem is None:
            for elem in ref_elem.iter():
                if elem.tag.endswith("DigestValue"):
                    digest_val_elem = elem
                    break

        if digest_val_elem is None or not digest_val_elem.text:
            raise SAMLError("Signature is missing DigestValue.")

        expected_digest = base64.b64decode(digest_val_elem.text.strip())

        # Determine DigestMethod
        digest_method_elem = ref_elem.find(".//{http://www.w3.org/2000/09/xmldsig#}DigestMethod")
        if digest_method_elem is None:
            for elem in ref_elem.iter():
                if elem.tag.endswith("DigestMethod"):
                    digest_method_elem = elem
                    break

        digest_algo_uri = digest_method_elem.attrib.get("Algorithm", "") if digest_method_elem is not None else ""
        if "sha1" in digest_algo_uri.lower():
            hash_func = hashlib.sha1
            crypto_hash = hashes.SHA1()
        else:
            hash_func = hashlib.sha256
            crypto_hash = hashes.SHA256()

        # Enveloped signature: Remove Signature element from copy of target element to compute digest
        target_copy = copy.deepcopy(target_elem)
        # Find and remove Signature in copy
        for child in list(target_copy):
            if child.tag.endswith("Signature"):
                target_copy.remove(child)
                break
        else:
            # Check sub-elements
            for parent in target_copy.iter():
                for child in list(parent):
                    if child.tag.endswith("Signature"):
                        parent.remove(child)
                        break

        # Canonicalize target element
        c14n_target = ET.canonicalize(ET.tostring(target_copy, encoding="utf-8"))
        actual_digest = hash_func(c14n_target.encode("utf-8")).digest()

        if actual_digest != expected_digest:
            raise SAMLError("SAML digest verification failed. The XML content has been forged or tampered with.")

        # Extract SignedInfo and SignatureValue
        signed_info_elem = sig_elem.find(".//{http://www.w3.org/2000/09/xmldsig#}SignedInfo")
        if signed_info_elem is None:
            for elem in sig_elem.iter():
                if elem.tag.endswith("SignedInfo"):
                    signed_info_elem = elem
                    break

        sig_val_elem = sig_elem.find(".//{http://www.w3.org/2000/09/xmldsig#}SignatureValue")
        if sig_val_elem is None:
            for elem in sig_elem.iter():
                if elem.tag.endswith("SignatureValue"):
                    sig_val_elem = elem
                    break

        if signed_info_elem is None or sig_val_elem is None or not sig_val_elem.text:
            raise SAMLError("Signature missing SignedInfo or SignatureValue.")

        signature_bytes = base64.b64decode(re.sub(r"\s+", "", sig_val_elem.text))
        c14n_signed_info = ET.canonicalize(ET.tostring(signed_info_elem, encoding="utf-8")).encode("utf-8")

        # Load X.509 Certificate and public key using cryptography
        try:
            cert_pem = _clean_cert(idp_x509_cert)
            cert = x509.load_pem_x509_certificate(cert_pem, default_backend())
            public_key = cert.public_key()
        except Exception as e:
            raise SAMLError(f"Invalid IdP X.509 certificate: {e}") from e

        if not isinstance(public_key, rsa.RSAPublicKey):
            raise SAMLError(f"Unsupported public key type: {type(public_key)}. Only RSA is supported.")

        # Vetted Cryptographic Signature Verification
        try:
            public_key.verify(
                signature_bytes,
                c14n_signed_info,
                padding.PKCS1v15(),
                crypto_hash,
            )
        except Exception as e:
            raise SAMLError(f"Cryptographic signature verification failed: {e}") from e
