"""Captive portal routes (client-facing).

Flow: index -> phone -> verify (OTP) -> tariffs -> payment -> success.
Registration state is kept in the signed session cookie under ``portal``.
The client only ever types a phone number; IP/MAC come from the DHCP lease.
"""
import datetime as dt

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import flash, render
from ..services import clients as clients_service
from ..services import otp as otp_service
from ..services import payments as payments_service
from ..services import portal as portal_service
from ..services import sms as sms_service
from ..services.access_control import activate_client
from ..services.logs import log_access
from ..services.tariffs import get_tariff, list_tariffs

router = APIRouter(prefix="/portal", tags=["portal"])


def _state(request: Request) -> dict:
    return request.session.setdefault("portal", {})


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=303)


@router.get("")
def index(request: Request):
    return render(request, "portal_index.html")


@router.get("/phone")
def phone_form(request: Request):
    return render(request, "portal_phone.html")


@router.post("/send-otp")
def send_otp(request: Request, phone: str = Form(...), db: Session = Depends(get_db)):
    phone = phone.strip()
    if not phone:
        flash(request, "Введите номер телефона.", "danger")
        return _redirect("/portal/phone")

    # Determine the client's device from its IP via the MikroTik DHCP lease.
    client_ip = portal_service.get_client_ip(request)
    info = portal_service.resolve_device_info(db, client_ip)

    if not info["found"] and portal_service.lease_required():
        flash(
            request,
            info.get("message")
            or "Не удалось определить устройство. Переподключитесь к Wi-Fi.",
            "danger",
        )
        return render(request, "portal_phone.html")

    client = clients_service.upsert_registration(
        db,
        phone=phone,
        ip_address=info.get("ip"),
        mac_address=info.get("mac"),
        hostname=info.get("hostname"),
        mikrotik_id=info.get("mikrotik_id"),
    )

    code = otp_service.create_otp(db, phone)
    message = f"Ваш код подтверждения {settings.APP_NAME}: {code}"
    sms_result = sms_service.send_sms(db, phone, message)
    log_access(db, action="send_otp", client_id=client.id)

    state = _state(request)
    state.update(
        {
            "phone": phone,
            "client_id": client.id,
            "ip": info.get("ip"),
            "mac": info.get("mac"),
            "hostname": info.get("hostname"),
            "verified": False,
            "tariff_id": None,
            "payment_id": None,
        }
    )
    # MVP convenience: surface the code on screen when using the mock provider.
    if settings.SMS_PROVIDER == "mock":
        state["dev_code"] = code

    if not sms_result["success"]:
        flash(request, "Не удалось отправить SMS. Попробуйте ещё раз.", "danger")
    if not info["found"]:
        flash(
            request,
            "Внимание: устройство не найдено в DHCP MikroTik (MVP-режим продолжает работу).",
            "warning",
        )
    return _redirect("/portal/verify")


@router.get("/verify")
def verify_form(request: Request):
    state = _state(request)
    if not state.get("phone"):
        return _redirect("/portal/phone")
    return render(
        request,
        "portal_verify.html",
        phone=state.get("phone"),
        dev_code=state.get("dev_code"),
    )


@router.post("/verify-otp")
def verify_otp(request: Request, code: str = Form(...), db: Session = Depends(get_db)):
    state = _state(request)
    phone = state.get("phone")
    if not phone:
        return _redirect("/portal/phone")

    ok, message = otp_service.verify_otp(db, phone, code.strip())
    log_access(db, action="verify_otp", client_id=state.get("client_id"),
               error_message=None if ok else message)
    if not ok:
        flash(request, message, "danger")
        return _redirect("/portal/verify")

    state["verified"] = True
    state.pop("dev_code", None)
    client = clients_service.get_client(db, state.get("client_id"))
    if client:
        client.phone_verified = True
        db.commit()
    flash(request, "Номер подтверждён. Выберите тариф.", "success")
    return _redirect("/portal/tariffs")


@router.get("/tariffs")
def tariffs_page(request: Request, db: Session = Depends(get_db)):
    state = _state(request)
    if not state.get("verified"):
        flash(request, "Сначала подтвердите номер телефона.", "warning")
        return _redirect("/portal/phone")
    return render(request, "portal_tariffs.html", tariffs=list_tariffs(db, only_active=True))


@router.post("/select-tariff")
def select_tariff(request: Request, tariff_id: int = Form(...), db: Session = Depends(get_db)):
    state = _state(request)
    if not state.get("verified"):
        return _redirect("/portal/phone")
    tariff = get_tariff(db, tariff_id)
    if not tariff or not tariff.is_active:
        flash(request, "Тариф недоступен.", "danger")
        return _redirect("/portal/tariffs")
    state["tariff_id"] = tariff.id
    state["payment_id"] = None
    return _redirect("/portal/payment")


@router.get("/payment")
def payment_page(request: Request, db: Session = Depends(get_db)):
    state = _state(request)
    tariff_id = state.get("tariff_id")
    if not state.get("verified") or not tariff_id:
        return _redirect("/portal/tariffs")
    tariff = get_tariff(db, tariff_id)
    if not tariff:
        return _redirect("/portal/tariffs")

    payment = None
    if state.get("payment_id"):
        payment = payments_service.get_payment(db, state["payment_id"])
    return render(request, "portal_payment.html", tariff=tariff, payment=payment)


@router.post("/create-payment")
def create_payment(request: Request, db: Session = Depends(get_db)):
    state = _state(request)
    tariff_id = state.get("tariff_id")
    client_id = state.get("client_id")
    if not state.get("verified") or not tariff_id or not client_id:
        return _redirect("/portal/tariffs")

    client = clients_service.get_client(db, client_id)
    tariff = get_tariff(db, tariff_id)
    if not client or not tariff:
        flash(request, "Ошибка создания платежа.", "danger")
        return _redirect("/portal/tariffs")

    # Mark the client as pending payment.
    from ..models import STATUS_PENDING_PAYMENT

    client.status = STATUS_PENDING_PAYMENT
    client.tariff_id = tariff.id
    db.commit()

    payment, info = payments_service.create_payment(db, client, tariff)
    log_access(
        db,
        action="create_payment",
        client_id=client.id,
        error_message=None if info.get("success", True) else info.get("error"),
    )
    state["payment_id"] = payment.id

    # Real gateway: send the user straight to the external payment page.
    pay_url = info.get("payment_url")
    if pay_url:
        return _redirect(pay_url)
    if payment.status == "failed":
        flash(request, "Не удалось создать платёж. Попробуйте позже.", "danger")
        return _redirect("/portal/payment-failed")
    return _redirect("/portal/payment")


@router.post("/mock-pay")
def mock_pay(request: Request, db: Session = Depends(get_db)):
    state = _state(request)
    payment_id = state.get("payment_id")
    client_id = state.get("client_id")
    if not payment_id or not client_id:
        return _redirect("/portal/payment")

    payment = payments_service.get_payment(db, payment_id)
    client = clients_service.get_client(db, client_id)
    if not payment or not client:
        flash(request, "Платёж не найден.", "danger")
        return _redirect("/portal/payment-failed")

    payments_service.mark_paid(db, payment)
    log_access(db, action="payment_paid", client_id=client.id)

    tariff = get_tariff(db, payment.tariff_id) if payment.tariff_id else None
    if tariff:
        client.tariff_id = tariff.id
        client.expires_at = dt.datetime.utcnow() + dt.timedelta(days=tariff.validity_days)
        db.commit()

    result = activate_client(db, client, reason="payment")
    state["activated"] = True
    state["mikrotik_ok"] = result.get("mikrotik_ok")
    return _redirect("/portal/success")


@router.get("/success")
def success_page(request: Request, db: Session = Depends(get_db)):
    state = _state(request)
    client = clients_service.get_client(db, state.get("client_id")) if state.get("client_id") else None
    return render(
        request,
        "portal_success.html",
        client=client,
        mikrotik_ok=state.get("mikrotik_ok", False),
    )


@router.get("/payment-failed")
def payment_failed(request: Request):
    return render(request, "portal_failed.html", reason="Платёж не был завершён.")


@router.get("/status")
def status_page(request: Request, db: Session = Depends(get_db)):
    state = _state(request)
    client = None
    if state.get("client_id"):
        client = clients_service.get_client(db, state["client_id"])
    if client is None:
        client_ip = portal_service.get_client_ip(request)
        if client_ip:
            client = clients_service.get_client_by_ip(db, client_ip)
    tariff = get_tariff(db, client.tariff_id) if client and client.tariff_id else None
    return render(request, "portal_status.html", client=client, tariff=tariff)
