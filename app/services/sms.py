"""SMS provider abstraction.

Provider and credentials come from the runtime settings store (admin panel)
with .env as fallback. MockSMSProvider just logs; HTTPSMSProvider posts to a
configurable REST gateway.
"""
import json
import logging

import httpx
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from . import settings_store

logger = logging.getLogger("wam.sms")


class SMSProvider:
    name = "base"

    def send_sms(self, phone: str, message: str) -> dict:  # pragma: no cover
        raise NotImplementedError

    def send_otp(self, phone: str, code: str) -> dict:
        message = f"Your {settings.APP_NAME} verification code is: {code}"
        return self.send_sms(phone, message)


class MockSMSProvider(SMSProvider):
    name = "mock"

    def send_sms(self, phone: str, message: str) -> dict:
        logger.info("[MOCK SMS] to=%s message=%s", phone, message)
        return {"success": True, "provider": self.name, "message": message}


class HTTPSMSProvider(SMSProvider):
    """Generic HTTP SMS gateway configured via the settings store / .env."""

    name = "http"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def send_sms(self, phone: str, message: str) -> dict:
        cfg = self.cfg
        url = cfg.get("SMS_API_URL")
        if not url:
            return {"success": False, "provider": self.name,
                    "error": "SMS_API_URL is not configured"}

        params = {
            cfg.get("SMS_PHONE_PARAM", "phone"): phone,
            cfg.get("SMS_TEXT_PARAM", "text"): message,
        }
        if cfg.get("SMS_SENDER"):
            params[cfg.get("SMS_SENDER_PARAM", "from")] = cfg["SMS_SENDER"]
        if cfg.get("SMS_EXTRA_PARAMS"):
            try:
                params.update(json.loads(cfg["SMS_EXTRA_PARAMS"]))
            except Exception:  # noqa: BLE001
                logger.warning("SMS_EXTRA_PARAMS is not valid JSON; ignored")

        headers = {}
        if cfg.get("SMS_API_KEY"):
            prefix = cfg.get("SMS_API_AUTH_PREFIX", "")
            if prefix and not prefix.endswith(" "):
                prefix += " "
            headers[cfg.get("SMS_API_AUTH_HEADER", "Authorization")] = (
                f"{prefix}{cfg['SMS_API_KEY']}"
            )

        try:
            with httpx.Client(timeout=15) as client:
                if cfg.get("SMS_API_METHOD", "POST").upper() == "GET":
                    resp = client.get(url, params=params, headers=headers)
                elif settings_store.as_bool(cfg.get("SMS_JSON_BODY", "true")):
                    resp = client.post(url, json=params, headers=headers)
                else:
                    resp = client.post(url, data=params, headers=headers)
            ok = 200 <= resp.status_code < 300
            return {
                "success": ok,
                "provider": self.name,
                "message": message,
                "error": None if ok else f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "provider": self.name, "error": str(exc)}


def get_sms_provider(cfg: dict) -> SMSProvider:
    if cfg.get("SMS_PROVIDER", "mock") == "http":
        return HTTPSMSProvider(cfg)
    return MockSMSProvider()


def send_sms(db: Session, phone: str, message: str):
    """Send an SMS using the configured provider, logging to sms_logs."""
    cfg = settings_store.effective(db)
    provider = get_sms_provider(cfg)
    error_message = None
    try:
        result = provider.send_sms(phone, message)
        status = "sent" if result.get("success") else "failed"
        if not result.get("success"):
            error_message = result.get("error", "unknown error")
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error_message = str(exc)

    log = models.SMSLog(
        phone=phone,
        message=message,
        provider=provider.name,
        status=status,
        error_message=error_message,
    )
    db.add(log)
    db.commit()
    return {"success": status == "sent", "status": status, "error": error_message}
