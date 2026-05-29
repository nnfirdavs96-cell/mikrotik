"""Payment provider abstraction + payment record helpers.

The MockPaymentProvider marks a payment as paid immediately when the client
presses the test-payment button. A real e-wallet integration would implement
PaymentProvider and be registered in get_payment_provider().
"""
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..models import utcnow


class PaymentProvider:
    name = "base"

    def create_payment(self, client_id: int, tariff_id: int, amount: float) -> dict:
        raise NotImplementedError  # pragma: no cover

    def check_payment_status(self, payment_id) -> dict:
        raise NotImplementedError  # pragma: no cover

    def handle_webhook(self, payload: dict) -> dict:
        raise NotImplementedError  # pragma: no cover


class MockPaymentProvider(PaymentProvider):
    name = "mock"

    def create_payment(self, client_id: int, tariff_id: int, amount: float) -> dict:
        # No external call for the mock provider.
        return {"success": True, "provider_payment_id": None, "status": "pending"}

    def check_payment_status(self, payment_id) -> dict:
        return {"success": True, "status": "paid"}

    def handle_webhook(self, payload: dict) -> dict:
        return {"success": True, "status": payload.get("status", "paid")}


class HTTPPaymentProvider(PaymentProvider):
    """Generic HTTP payment gateway.

    Creates a payment via PAYMENT_API_URL and expects the response JSON to
    contain a redirect URL (PAYMENT_PAY_URL_FIELD) and a payment id
    (PAYMENT_ID_FIELD). The gateway later confirms via POST /api/payments/
    webhook and redirects the user to PAYMENT_RETURN_URL.
    """

    name = "http"

    def _base(self) -> str:
        return settings.PUBLIC_BASE_URL.rstrip("/")

    def create_payment(self, client_id: int, tariff_id: int, amount: float) -> dict:
        if not settings.PAYMENT_API_URL:
            return {"success": False, "status": "failed",
                    "error": "PAYMENT_API_URL is not configured"}

        payload = {
            "amount": amount,
            "currency": settings.DEFAULT_CURRENCY,
            "client_id": client_id,
            "tariff_id": tariff_id,
            "return_url": settings.PAYMENT_RETURN_URL or f"{self._base()}/portal/success",
            "callback_url": settings.PAYMENT_CALLBACK_URL or f"{self._base()}/api/payments/webhook",
        }
        headers = {}
        if settings.PAYMENT_API_KEY:
            prefix = settings.PAYMENT_API_AUTH_PREFIX
            if prefix and not prefix.endswith(" "):
                prefix += " "
            headers[settings.PAYMENT_API_AUTH_HEADER] = f"{prefix}{settings.PAYMENT_API_KEY}"
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.post(settings.PAYMENT_API_URL, json=payload, headers=headers)
            if not (200 <= resp.status_code < 300):
                return {"success": False, "status": "failed",
                        "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                data = {}
            pid = data.get(settings.PAYMENT_ID_FIELD)
            return {
                "success": True,
                "status": "pending",
                "provider_payment_id": str(pid) if pid is not None else None,
                "payment_url": data.get(settings.PAYMENT_PAY_URL_FIELD),
            }
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "status": "failed", "error": str(exc)}

    def check_payment_status(self, payment_id) -> dict:
        return {"success": True, "status": "pending"}

    def handle_webhook(self, payload: dict) -> dict:
        return {"success": True, "status": payload.get("status", "paid")}


_PROVIDERS = {
    "mock": MockPaymentProvider,
    "http": HTTPPaymentProvider,
}


def get_payment_provider() -> PaymentProvider:
    cls = _PROVIDERS.get(settings.PAYMENT_PROVIDER, MockPaymentProvider)
    return cls()


def create_payment(
    db: Session, client: models.Client, tariff: models.Tariff
):
    """Create a payment record. Returns (payment, info).

    ``info`` carries provider extras such as ``payment_url`` (for real
    gateways) so the portal can redirect the user to the payment page.
    """
    provider = get_payment_provider()
    info = provider.create_payment(client.id, tariff.id, tariff.price)
    payment = models.Payment(
        client_id=client.id,
        tariff_id=tariff.id,
        amount=tariff.price,
        currency=tariff.currency,
        provider=provider.name,
        provider_payment_id=info.get("provider_payment_id"),
        status="pending",
    )
    if not info.get("success", True):
        payment.status = "failed"
        payment.error_message = info.get("error")
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment, info


def mark_paid(db: Session, payment: models.Payment) -> models.Payment:
    payment.status = "paid"
    payment.paid_at = utcnow()
    payment.error_message = None
    db.commit()
    db.refresh(payment)
    return payment


def mark_failed(db: Session, payment: models.Payment, error: str) -> models.Payment:
    payment.status = "failed"
    payment.error_message = error
    db.commit()
    db.refresh(payment)
    return payment


def get_payment(db: Session, payment_id: int) -> Optional[models.Payment]:
    return db.query(models.Payment).filter(models.Payment.id == payment_id).first()


def list_payments_for_client(db: Session, client_id: int):
    return (
        db.query(models.Payment)
        .filter(models.Payment.client_id == client_id)
        .order_by(models.Payment.id.desc())
        .all()
    )
