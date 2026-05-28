"""One-time-password (OTP) generation and verification.

Codes are never stored in clear text — only a salted SHA-256 hash is kept.
Codes are valid for OTP_TTL_MINUTES and allow at most OTP_MAX_ATTEMPTS tries.
"""
import datetime as dt
import hashlib
import random

from sqlalchemy.orm import Session

from .. import models
from ..config import settings


def generate_otp() -> str:
    """Generate a numeric OTP of the configured length."""
    length = max(4, min(8, settings.OTP_LENGTH))
    low = 10 ** (length - 1)
    high = (10 ** length) - 1
    return str(random.randint(low, high))


def hash_otp(code: str) -> str:
    """Deterministic salted hash so we can look the code up later."""
    salted = f"{code}:{settings.SECRET_KEY}".encode("utf-8")
    return hashlib.sha256(salted).hexdigest()


def expire_old_otps(db: Session, phone: str) -> None:
    """Mark previous unused codes for this phone as used."""
    now = dt.datetime.utcnow()
    db.query(models.OTPCode).filter(
        models.OTPCode.phone == phone,
        models.OTPCode.is_used.is_(False),
    ).update({models.OTPCode.is_used: True}, synchronize_session=False)
    db.commit()
    # Touch ``now`` to keep linters happy and document intent.
    _ = now


def create_otp(db: Session, phone: str) -> str:
    """Create a fresh OTP, invalidating older ones. Returns the plaintext code."""
    expire_old_otps(db, phone)
    code = generate_otp()
    expires_at = dt.datetime.utcnow() + dt.timedelta(minutes=settings.OTP_TTL_MINUTES)
    otp = models.OTPCode(
        phone=phone,
        code_hash=hash_otp(code),
        expires_at=expires_at,
        is_used=False,
        attempts=0,
    )
    db.add(otp)
    db.commit()
    return code


def check_attempts(otp: models.OTPCode) -> bool:
    """Return True while the code still has attempts left."""
    return otp.attempts < settings.OTP_MAX_ATTEMPTS


def verify_otp(db: Session, phone: str, code: str):
    """Verify a code for a phone.

    Returns a tuple (ok: bool, message: str).
    """
    now = dt.datetime.utcnow()
    otp = (
        db.query(models.OTPCode)
        .filter(
            models.OTPCode.phone == phone,
            models.OTPCode.is_used.is_(False),
        )
        .order_by(models.OTPCode.created_at.desc())
        .first()
    )

    if not otp:
        return False, "Код не найден. Запросите новый код."

    if otp.expires_at < now:
        otp.is_used = True
        db.commit()
        return False, "Срок действия кода истёк. Запросите новый код."

    if not check_attempts(otp):
        otp.is_used = True
        db.commit()
        return False, "Превышено число попыток. Запросите новый код."

    if otp.code_hash != hash_otp(code):
        otp.attempts += 1
        db.commit()
        remaining = max(0, settings.OTP_MAX_ATTEMPTS - otp.attempts)
        if remaining == 0:
            otp.is_used = True
            db.commit()
            return False, "Неверный код. Попытки исчерпаны, запросите новый код."
        return False, f"Неверный код. Осталось попыток: {remaining}."

    otp.is_used = True
    db.commit()
    return True, "Код подтверждён."
