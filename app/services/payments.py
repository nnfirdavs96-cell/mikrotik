"""Payment provider abstraction + payment record helpers.

The MockPaymentProvider marks a payment as paid immediately when the client
presses the test-payment button. A real e-wallet integration would implement
PaymentProvider and be registered in get_payment_provider().
"""
from typing import Optional

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


_PROVIDERS = {
    "mock": MockPaymentProvider,
}


def get_payment_provider() -> PaymentProvider:
    cls = _PROVIDERS.get(settings.PAYMENT_PROVIDER, MockPaymentProvider)
    return cls()


def create_payment(
    db: Session, client: models.Client, tariff: models.Tariff
) -> models.Payment:
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
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


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
