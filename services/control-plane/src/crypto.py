"""
Secret Encryption & Decryption Module
Implements AES-256-GCM authenticated encryption for credential storage.
Ensures zero plaintext leakage in database, logs, or API responses.
"""
import os
import json
import base64
import hashlib
from typing import Any, Union, Dict, List
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_master_key() -> bytes:
    """
    Derives 256-bit (32 bytes) master key from environment or fallback dev key.
    """
    raw_key = os.environ.get("CAPSULE_SECRET_KEY") or os.environ.get("CAPSULE_MASTER_KEY")
    if not raw_key:
        raw_key = "capsule-platform-dev-master-secret-key-32b"
    return hashlib.sha256(raw_key.encode("utf-8")).digest()


def encrypt_secret(data: Union[Dict[str, Any], str, List[Any], int, float, bool]) -> str:
    """
    Encrypts arbitrary data using AES-256-GCM.
    Returns base64-encoded string containing 12-byte nonce + ciphertext + 16-byte tag.
    """
    if isinstance(data, (dict, list, int, float, bool)):
        plaintext = json.dumps(data, separators=(",", ":")).encode("utf-8")
    elif isinstance(data, str):
        plaintext = data.encode("utf-8")
    elif isinstance(data, bytes):
        plaintext = data
    else:
        plaintext = str(data).encode("utf-8")

    key = _get_master_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # Standard 96-bit nonce for AES-GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    payload = nonce + ciphertext
    return base64.b64encode(payload).decode("utf-8")


def decrypt_secret(encrypted_b64: str) -> Any:
    """
    Decrypts base64-encoded AES-256-GCM payload.
    Returns parsed JSON object or raw string.
    """
    try:
        raw = base64.b64decode(encrypted_b64)
        if len(raw) < 28:  # 12-byte nonce + 16-byte minimum tag
            raise ValueError("Invalid encrypted payload length")

        nonce = raw[:12]
        ciphertext = raw[12:]
        key = _get_master_key()
        aesgcm = AESGCM(key)
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        plaintext_str = plaintext_bytes.decode("utf-8")
        try:
            return json.loads(plaintext_str)
        except json.JSONDecodeError:
            return plaintext_str
    except Exception as e:
        raise ValueError(f"Failed to decrypt secret: {str(e)}") from e


SENSITIVE_KEY_EXACT = {
    "secret",
    "password",
    "token",
    "authorization",
    "bot_token",
    "client_secret",
    "private_key",
    "api_key",
    "access_token",
    "refresh_token",
    "signing_secret",
    "webhook_secret",
}


def _is_sensitive_key(k: str) -> bool:
    clean = k.lower().strip()
    if clean in SENSITIVE_KEY_EXACT:
        return True
    if any(clean.endswith(s) for s in ["_token", "_secret", "_password", "_api_key"]):
        return True
    if clean.endswith("_key") and clean not in ("app_key", "capability_key", "key_id"):
        return True
    return False


def mask_sensitive_data(data: Any) -> Any:
    """
    Recursively masks sensitive values in dictionaries and lists for safe logging.
    Keys matching sensitive names are replaced with '[REDACTED]'.
    """
    if isinstance(data, dict):
        masked: Dict[str, Any] = {}
        for k, v in data.items():
            if _is_sensitive_key(k) and not isinstance(v, bool):
                masked[k] = "[REDACTED]"
            else:
                masked[k] = mask_sensitive_data(v)
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    return data
