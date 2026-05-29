"""SMS provider abstraction.

For the MVP a MockSMSProvider just records the message in sms_logs and prints
it to the console. The architecture lets you plug a real provider later by
implementing SMSProvider.send_sms and registering it in get_sms_provider().
"""
import json
import logging
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from .. import models
from ..config import settings

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
        # In the MVP the "delivery" is just a log line.
        logger.info("[MOCK SMS] to=%s message=%s", phone, message)
        return {"success": True, "provider": self.name, "message": message}


class HTTPSMSProvider(SMSProvider):
    """Generic HTTP SMS gateway driven entirely by .env settings.

    Works with most REST SMS APIs: configure SMS_API_URL, SMS_API_KEY and the
    field names (SMS_PHONE_PARAM / SMS_TEXT_PARAM / SMS_SENDER_PARAM). Use
    SMS_API_METHOD to pick GET or POST and SMS_JSON_BODY for JSON vs form.
    """

    name = "http"

    def send_sms(self, phone: str, message: str) -> dict:
        if not settings.SMS_API_URL:
            return {
                "success": False,
                "provider": self.name,
                "error": "SMS_API_URL is not configured",
            }

        params = {
            settings.SMS_PHONE_PARAM: phone,
            settings.SMS_TEXT_PARAM: message,
        }
        if settings.SMS_SENDER:
            params[settings.SMS_SENDER_PARAM] = settings.SMS_SENDER
        if settings.SMS_EXTRA_PARAMS:
            try:
                params.update(json.loads(settings.SMS_EXTRA_PARAMS))
            except Exception:  # noqa: BLE001
                logger.warning("SMS_EXTRA_PARAMS is not valid JSON; ignored")

        headers = {}
        if settings.SMS_API_KEY:
            prefix = settings.SMS_API_AUTH_PREFIX
            if prefix and not prefix.endswith(" "):
                prefix += " "
            headers[settings.SMS_API_AUTH_HEADER] = f"{prefix}{settings.SMS_API_KEY}"

        try:
            with httpx.Client(timeout=15) as client:
                if settings.SMS_API_METHOD.upper() == "GET":
                    resp = client.get(settings.SMS_API_URL, params=params, headers=headers)
                elif settings.SMS_JSON_BODY:
                    resp = client.post(settings.SMS_API_URL, json=params, headers=headers)
                else:
                    resp = client.post(settings.SMS_API_URL, data=params, headers=headers)
            ok = 200 <= resp.status_code < 300
            return {
                "success": ok,
                "provider": self.name,
                "message": message,
                "error": None if ok else f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "provider": self.name, "error": str(exc)}


_PROVIDERS = {
    "mock": MockSMSProvider,
    "http": HTTPSMSProvider,
}


def get_sms_provider() -> SMSProvider:
    cls = _PROVIDERS.get(settings.SMS_PROVIDER, MockSMSProvider)
    return cls()


def send_sms(db: Session, phone: str, message: str, log_otp_code: Optional[str] = None):
    """Send an SMS, persisting the attempt to sms_logs."""
    provider = get_sms_provider()
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
