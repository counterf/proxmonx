"""Password hashing and verification utilities."""

from __future__ import annotations

import hashlib
import hmac
import os


def hash_password(password: str) -> str:
    """Hash a password using scrypt. Returns 'scrypt:<salt_hex>:<hash_hex>'."""
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=64,
    )
    return f"scrypt:{salt.hex()}:{derived.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a scrypt hash string. Timing-safe."""
    try:
        parts = hashed.split(":")
        if len(parts) != 3 or parts[0] != "scrypt":
            return False
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
    except (ValueError, IndexError):
        return False

    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=64,
    )
    return hmac.compare_digest(derived, expected)
