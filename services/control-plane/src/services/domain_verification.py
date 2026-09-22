"""
Domain Verification Service for Enterprise SSO.
Verifies domain ownership via DNS TXT records (_capsule-challenge.<domain> or <domain>).
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Test mock resolver for hermetic integration tests
_TEST_DNS_RECORDS: Dict[str, List[str]] = {}


def register_test_dns_record(domain: str, txt_records: List[str]) -> None:
    """Registers mock DNS TXT records for hermetic testing."""
    _TEST_DNS_RECORDS[domain.lower().strip()] = txt_records


def clear_test_dns_records() -> None:
    """Clears all mock DNS TXT records."""
    _TEST_DNS_RECORDS.clear()


async def verify_domain_ownership(domain: str, expected_token: str) -> bool:
    """
    Checks if expected_token is present in DNS TXT records for the domain.
    Checks test mock resolver first, then live DNS.
    """
    clean_domain = domain.lower().strip()

    # 1. Check test registry (hermetic tests)
    if clean_domain in _TEST_DNS_RECORDS:
        records = _TEST_DNS_RECORDS[clean_domain]
        return any(expected_token in r for r in records)

    challenge_host = f"_capsule-challenge.{clean_domain}"
    if challenge_host in _TEST_DNS_RECORDS:
        records = _TEST_DNS_RECORDS[challenge_host]
        return any(expected_token in r for r in records)

    # 2. Live DNS check (production / staging)
    try:
        import dns.resolver  # if dnspython installed
        for query_host in [challenge_host, clean_domain]:
            try:
                answers = dns.resolver.resolve(query_host, "TXT")
                for rdata in answers:
                    txt_val = "".join([b.decode("utf-8") if isinstance(b, bytes) else str(b) for b in rdata.strings])
                    if expected_token in txt_val:
                        return True
            except Exception:
                continue
    except ImportError:
        logger.warning("dnspython not installed, falling back to mock resolver only.")

    return False
