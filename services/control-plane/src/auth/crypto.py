"""
Re-export crypto functions for backward compatibility.
"""
from crypto import (
    encrypt_secret,
    decrypt_secret,
    mask_sensitive_data,
    SENSITIVE_KEY_EXACT,
)

__all__ = [
    "encrypt_secret",
    "decrypt_secret",
    "mask_sensitive_data",
    "SENSITIVE_KEY_EXACT",
]
