"""Encryption helpers for secrets at rest (MikroTik passwords).

A transparent SQLAlchemy ``EncryptedString`` type stores ciphertext in the
database while the Python attribute stays plaintext. Decryption is
backward-compatible: legacy plaintext values (stored before encryption was
enabled) are returned as-is, so existing data keeps working.
"""
import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import String, TypeDecorator

from .config import settings


@lru_cache
def _fernet() -> Fernet:
    key = (settings.ENCRYPTION_KEY or "").strip()
    if not key:
        # Derive a valid Fernet key from SECRET_KEY for zero-config operation.
        key = base64.urlsafe_b64encode(
            hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        ).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value):
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value):
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        # Legacy plaintext (pre-encryption) or wrong key: return unchanged.
        return value


class EncryptedString(TypeDecorator):
    """String column that is encrypted at rest and decrypted on read."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
