"""REST API: payment webhook. Requires X-API-Key.

A real payment provider would POST here when a payment changes state. When the
status is ``paid`` we mark the payment paid, activate the client and add its IP
to MikroTik allowed_clients.
"""
import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_api_key
from ..models import Payment, utcnow
from ..schemas import PaymentWebhook
from ..services import clients as clients_service
from ..services import payments as payments_service
from ..services.access_control import activate_client
from ..services.logs import log_access
from ..services.tariffs import get_tariff

router = APIRouter(prefix="/api/payments", tags=["payments"], dependencies=[Depends(require_api_key)])


@router.post("/webhook")
def payment_webhook(payload: PaymentWebhook, db: Session = Depends(get_db)):
    payment = None
    if payload.payment_id:
        payment = payments_service.get_payment(db, payload.payment_id)
    if payment is None and payload.provider_payment_id:
        payment = (
            db.query(Payment)
            .filter(Payment.provider_payment_id == payload.provider_payment_id)
            .first()
        )
    if payment is None:
        return {"success": False, "message": "Payment not found"}

    if payload.status != "paid":
        payments_service.mark_failed(db, payment, error=f"status={payload.status}")
        return {"success": True, "message": f"Payment marked {payload.status}"}

    payments_service.mark_paid(db, payment)
    log_access(db, action="payment_paid", client_id=payment.client_id)

    client = clients_service.get_client(db, payment.client_id) if payment.client_id else None
    if client is None:
        return {"success": True, "message": "Payment paid, but no client linked"}

    tariff = get_tariff(db, payment.tariff_id) if payment.tariff_id else None
    if tariff:
        client.tariff_id = tariff.id
        client.expires_at = utcnow() + dt.timedelta(days=tariff.validity_days)
        db.commit()

    result = activate_client(db, client, reason="payment")
    return {"success": True, "message": "Payment paid and client activated", "mikrotik": result}
