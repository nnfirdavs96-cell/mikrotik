"""Runtime settings store: DB overrides on top of .env defaults.

Lets the admin panel configure integration settings (SMS / payment providers)
without editing .env. Values are stored as strings in the ``app_settings``
table; when a key is absent the value falls back to the .env default.
"""
from sqlalchemy.orm import Session

from .. import models
from ..config import settings as env_settings

SMS_KEYS = [
    "SMS_PROVIDER",
    "SMS_API_URL",
    "SMS_API_KEY",
    "SMS_API_METHOD",
    "SMS_API_AUTH_HEADER",
    "SMS_API_AUTH_PREFIX",
    "SMS_SENDER",
    "SMS_PHONE_PARAM",
    "SMS_TEXT_PARAM",
    "SMS_SENDER_PARAM",
    "SMS_EXTRA_PARAMS",
    "SMS_JSON_BODY",
]

PAYMENT_KEYS = [
    "PAYMENT_PROVIDER",
    "PAYMENT_API_URL",
    "PAYMENT_API_KEY",
    "PAYMENT_API_AUTH_HEADER",
    "PAYMENT_API_AUTH_PREFIX",
    "PAYMENT_RETURN_URL",
    "PAYMENT_CALLBACK_URL",
    "PAYMENT_PAY_URL_FIELD",
    "PAYMENT_ID_FIELD",
]

ACCESS_KEYS = ["ACCESS_MODE", "ACCESS_HOTSPOT_PROFILE"]

ALL_KEYS = SMS_KEYS + PAYMENT_KEYS + ACCESS_KEYS + ["PUBLIC_BASE_URL"]

# Fields that hold secrets — never rendered back to the form in clear text.
SECRET_KEYS = {"SMS_API_KEY", "PAYMENT_API_KEY"}

BOOL_KEYS = {"SMS_JSON_BODY"}


def _db_overrides(db: Session) -> dict:
    return {
        row.key: row.value
        for row in db.query(models.AppSetting).all()
        if row.value is not None
    }


def effective(db: Session) -> dict:
    """Effective integration config: DB override or .env default per key."""
    overrides = _db_overrides(db)
    out = {}
    for key in ALL_KEYS:
        if key in overrides:
            out[key] = overrides[key]
        else:
            default = getattr(env_settings, key, "")
            out[key] = str(default) if default is not None else ""
    return out


def as_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def save(db: Session, data: dict) -> None:
    """Upsert provided keys (only known keys are persisted)."""
    for key, value in data.items():
        if key not in ALL_KEYS:
            continue
        row = db.query(models.AppSetting).filter(models.AppSetting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(models.AppSetting(key=key, value=value))
    db.commit()
