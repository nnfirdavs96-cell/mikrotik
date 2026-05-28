"""SMS provider abstraction.

For the MVP a MockSMSProvider just records the message in sms_logs and prints
it to the console. The architecture lets you plug a real provider later by
implementing SMSProvider.send_sms and registering it in get_sms_provider().
"""
import logging
from typing import Optional

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


# Future real providers would be added to this registry.
_PROVIDERS = {
    "mock": MockSMSProvider,
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
