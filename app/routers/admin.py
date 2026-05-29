"""Admin panel routes (session-cookie protected)."""
import csv
import datetime as dt
import io
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import authenticate_admin
from ..config import settings
from ..database import get_db
from ..dependencies import flash, render, require_admin
from ..models import (
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    STATUS_EXPIRED,
    STATUS_INACTIVE,
    STATUS_PENDING_PAYMENT,
    AccessLog,
    Client,
    MikroTikDevice,
    Payment,
    SMSLog,
    Tariff,
)
from ..mikrotik.client import MikroTikError
from ..mikrotik.service import build_client, get_active_device, get_capsman_for_device
from ..services import clients as clients_service
from ..services import mikrotik_devices as devices_service
from ..services import settings_store
from ..services import sms as sms_service
from ..services import tariffs as tariffs_service
from ..services.access_control import (
    activate_client,
    block_client,
    deactivate_client,
)
from ..services.logs import log_access, recent_logs
from ..services.sync import sync_with_mikrotik

router = APIRouter(prefix="/admin", tags=["admin"])


def _bool(value: Optional[str]) -> bool:
    return str(value).lower() in {"on", "true", "1", "yes"}


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=303)


def _parse_dt(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _fmt_dt(value: Optional[dt.datetime]) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def _csv_response(filename: str, header: list, rows: list) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    # Prepend BOM so Excel opens UTF-8 (Cyrillic) correctly.
    content = "﻿" + buf.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@router.get("/login")
def login_form(request: Request):
    return render(request, "login.html")


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = authenticate_admin(db, username.strip(), password)
    if not admin:
        flash(request, "Неверный логин или пароль.", "danger")
        return _redirect("/admin/login")
    request.session["admin_id"] = admin.id
    flash(request, f"Добро пожаловать, {admin.username}!", "success")
    return _redirect("/admin")


@router.get("/logout")
def logout(request: Request):
    request.session.pop("admin_id", None)
    flash(request, "Вы вышли из системы.", "info")
    return _redirect("/admin/login")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    def count(status):
        return db.query(func.count(Client.id)).filter(Client.status == status).scalar()

    today = dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    payments_today = db.query(Payment).filter(
        Payment.status == "paid", Payment.paid_at >= today
    ).all()

    device = get_active_device(db)
    mk_status = "not_configured"
    allowed_count = None
    if device is not None:
        mk_client = build_client(device)
        try:
            mk_client.get_system_resource()
            allowed_count = len(mk_client.get_allowed_clients(settings.DEFAULT_ALLOWED_LIST))
            mk_status = "ok"
        except MikroTikError:
            mk_status = "error"
        finally:
            mk_client.close()

    stats = {
        "total": db.query(func.count(Client.id)).scalar(),
        "active": count(STATUS_ACTIVE),
        "inactive": count(STATUS_INACTIVE),
        "pending": count(STATUS_PENDING_PAYMENT),
        "expired": count(STATUS_EXPIRED),
        "blocked": count(STATUS_BLOCKED),
        "mikrotik_count": db.query(func.count(MikroTikDevice.id)).scalar(),
        "allowed_count": allowed_count,
        "payments_today_count": len(payments_today),
        "payments_today_sum": round(sum(p.amount for p in payments_today), 2),
    }
    return render(
        request,
        "admin_dashboard.html",
        stats=stats,
        device=device,
        mk_status=mk_status,
        logs=recent_logs(db, 10),
    )


# ---------------------------------------------------------------------------
# MikroTik devices
# ---------------------------------------------------------------------------
@router.get("/mikrotik")
def mikrotik_list(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    return render(request, "admin_mikrotik_devices.html", devices=devices_service.list_devices(db))


@router.get("/mikrotik/new")
def mikrotik_new(request: Request, admin=Depends(require_admin)):
    return render(request, "admin_mikrotik_form.html", device=None)


@router.post("/mikrotik/new")
def mikrotik_create(
    request: Request,
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(8728),
    username: str = Form(...),
    password: str = Form(...),
    use_ssl: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    comment: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    devices_service.create_device(
        db,
        name=name,
        host=host,
        port=port,
        username=username,
        password=password,
        use_ssl=_bool(use_ssl),
        is_active=_bool(is_active),
        comment=comment,
    )
    flash(request, "MikroTik добавлен.", "success")
    return _redirect("/admin/mikrotik")


@router.get("/mikrotik/{device_id}/edit")
def mikrotik_edit(request: Request, device_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    device = devices_service.get_device(db, device_id)
    if not device:
        flash(request, "Устройство не найдено.", "danger")
        return _redirect("/admin/mikrotik")
    return render(request, "admin_mikrotik_form.html", device=device)


@router.post("/mikrotik/{device_id}/edit")
def mikrotik_update(
    request: Request,
    device_id: int,
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(8728),
    username: str = Form(...),
    password: Optional[str] = Form(None),
    use_ssl: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    comment: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    device = devices_service.get_device(db, device_id)
    if not device:
        flash(request, "Устройство не найдено.", "danger")
        return _redirect("/admin/mikrotik")
    devices_service.update_device(
        db,
        device,
        name=name,
        host=host,
        port=port,
        username=username,
        password=password,  # empty keeps the old password
        use_ssl=_bool(use_ssl),
        is_active=_bool(is_active),
        comment=comment,
    )
    flash(request, "MikroTik обновлён.", "success")
    return _redirect("/admin/mikrotik")


@router.post("/mikrotik/{device_id}/test")
def mikrotik_test(request: Request, device_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    device = devices_service.get_device(db, device_id)
    if not device:
        flash(request, "Устройство не найдено.", "danger")
        return _redirect("/admin/mikrotik")
    result = devices_service.test_connection(db, device)
    if result.get("success"):
        flash(request, f"Подключение успешно: {device.name}", "success")
    else:
        flash(request, f"Ошибка подключения: {result.get('details') or result.get('message')}", "danger")
    return _redirect("/admin/mikrotik")


@router.post("/mikrotik/{device_id}/set-active")
def mikrotik_set_active(request: Request, device_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    device = devices_service.get_device(db, device_id)
    if not device:
        flash(request, "Устройство не найдено.", "danger")
        return _redirect("/admin/mikrotik")
    devices_service.set_active(db, device)
    flash(request, f"{device.name} теперь активный MikroTik.", "success")
    return _redirect("/admin/mikrotik")


@router.post("/mikrotik/{device_id}/delete")
def mikrotik_delete(request: Request, device_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    device = devices_service.get_device(db, device_id)
    if not device:
        flash(request, "Устройство не найдено.", "danger")
        return _redirect("/admin/mikrotik")
    devices_service.delete_device(db, device)
    flash(request, "Устройство удалено.", "info")
    return _redirect("/admin/mikrotik")


@router.get("/connected-clients")
def connected_clients(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    device = get_active_device(db)
    leases = []
    error = None
    if device is None:
        error = "Нет активного MikroTik устройства."
    else:
        mk_client = build_client(device)
        try:
            raw = mk_client.get_dhcp_leases()
            for lease in raw:
                registered = None
                if lease.get("mac_address"):
                    registered = clients_service.get_client_by_mac(db, lease["mac_address"])
                if registered is not None:
                    clients_service.touch_last_seen(db, registered)
                leases.append(
                    {
                        **lease,
                        "registered": registered is not None,
                        "client_id": registered.id if registered else None,
                        "client_status": registered.status if registered else None,
                    }
                )
        except MikroTikError as exc:
            error = f"MikroTik API connection failed: {exc}"
        finally:
            mk_client.close()
    return render(
        request,
        "admin_connected_clients.html",
        leases=leases,
        error=error,
        device=device,
        clients=clients_service.search_clients(db),
    )


@router.post("/connected-clients/bind")
def connected_bind(
    request: Request,
    client_id: int = Form(...),
    mac_address: str = Form(""),
    ip_address: str = Form(""),
    hostname: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    client = clients_service.get_client(db, client_id)
    if not client:
        flash(request, "Клиент не найден.", "danger")
        return _redirect("/admin/connected-clients")
    clients_service.bind_device(
        db, client, mac_address=mac_address, ip_address=ip_address, hostname=hostname
    )
    flash(request, f"Устройство привязано к клиенту #{client.id} ({client.phone}).", "success")
    return _redirect("/admin/connected-clients")


@router.get("/access-points")
def access_points(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    device = get_active_device(db)
    data = None
    error = None
    if device is None:
        error = "Нет активного MikroTik устройства."
    else:
        res = get_capsman_for_device(device)
        if res.get("success"):
            data = res
            # Cross-reference connected Wi-Fi clients with registered clients.
            for c in data["clients"]:
                reg = clients_service.get_client_by_mac(db, c["mac"]) if c.get("mac") else None
                c["registered"] = reg is not None
                c["client_status"] = reg.status if reg else None
        else:
            error = res.get("details") or res.get("message")
    return render(request, "admin_access_points.html", device=device, data=data, error=error)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@router.get("/clients")
def clients_list(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    status_int = None
    if status not in (None, "", "all"):
        try:
            status_int = int(status)
        except ValueError:
            status_int = None
    clients = clients_service.search_clients(db, query=q, status=status_int)
    return render(
        request,
        "admin_clients.html",
        clients=clients,
        q=q or "",
        status=status or "all",
    )


@router.get("/clients.csv")
def clients_csv(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    status_int = None
    if status not in (None, "", "all"):
        try:
            status_int = int(status)
        except ValueError:
            status_int = None
    clients = clients_service.search_clients(db, query=q, status=status_int)
    header = [
        "id", "phone", "phone_verified", "mac_address", "ip_address",
        "hostname", "status", "tariff", "mikrotik_id", "expires_at",
        "created_at", "activated_at", "deactivated_at",
    ]
    rows = [
        [
            c.id, c.phone, int(bool(c.phone_verified)), c.mac_address or "",
            c.ip_address or "", c.hostname or "", c.status_label,
            c.tariff.name if c.tariff else "", c.mikrotik_id or "",
            _fmt_dt(c.expires_at), _fmt_dt(c.created_at),
            _fmt_dt(c.activated_at), _fmt_dt(c.deactivated_at),
        ]
        for c in clients
    ]
    return _csv_response("clients.csv", header, rows)


@router.get("/clients/{client_id}/edit")
def client_edit_form(request: Request, client_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    client = clients_service.get_client(db, client_id)
    if not client:
        flash(request, "Клиент не найден.", "danger")
        return _redirect("/admin/clients")
    # Best-effort: load current DHCP leases so the admin can bind a device.
    leases = []
    device = get_active_device(db)
    if device is not None:
        mk_client = build_client(device)
        try:
            leases = mk_client.get_dhcp_leases()
        except MikroTikError:
            leases = []
        finally:
            mk_client.close()
    return render(
        request,
        "admin_client_edit.html",
        client=client,
        tariffs=tariffs_service.list_tariffs(db),
        devices=devices_service.list_devices(db),
        leases=leases,
    )


@router.post("/clients/{client_id}/edit")
def client_edit(
    request: Request,
    client_id: int,
    phone: str = Form(...),
    tariff_id: Optional[str] = Form(None),
    mikrotik_id: Optional[str] = Form(None),
    status: int = Form(...),
    expires_at: Optional[str] = Form(None),
    mac_address: str = Form(""),
    ip_address: str = Form(""),
    comment: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    client = clients_service.get_client(db, client_id)
    if not client:
        flash(request, "Клиент не найден.", "danger")
        return _redirect("/admin/clients")

    old_status = client.status
    old_ip = client.ip_address
    old_mac = client.mac_address
    client.phone = phone.strip()
    client.tariff_id = int(tariff_id) if tariff_id else None
    client.mikrotik_id = int(mikrotik_id) if mikrotik_id else None
    client.comment = comment
    client.expires_at = _parse_dt(expires_at)
    # MAC / IP are editable (Manual Admin Mode); blank clears the field.
    client.mac_address = mac_address.strip() or None
    client.ip_address = ip_address.strip() or None
    db.commit()

    # Handle status transitions through MikroTik (0<->1).
    if status != old_status:
        if status == STATUS_ACTIVE:
            activate_client(db, client)
        elif status in (STATUS_INACTIVE, STATUS_EXPIRED):
            deactivate_client(db, client, set_status=status)
        elif status == STATUS_BLOCKED:
            block_client(db, client)
        else:
            client.status = status
            db.commit()
    elif status == STATUS_ACTIVE and (
        client.ip_address != old_ip or client.mac_address != old_mac
    ):
        # Active client whose MAC/IP changed: re-push to MikroTik.
        activate_client(db, client)
    else:
        log_access(db, action="update_client", client_id=client.id, new_status=status)

    flash(request, "Клиент обновлён.", "success")
    return _redirect("/admin/clients")


@router.post("/clients/{client_id}/activate")
def client_activate(request: Request, client_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    client = clients_service.get_client(db, client_id)
    if not client:
        flash(request, "Клиент не найден.", "danger")
        return _redirect("/admin/clients")
    result = activate_client(db, client)
    _flash_mk(request, result, "Клиент активирован.")
    return _redirect("/admin/clients")


@router.post("/clients/{client_id}/deactivate")
def client_deactivate(request: Request, client_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    client = clients_service.get_client(db, client_id)
    if not client:
        flash(request, "Клиент не найден.", "danger")
        return _redirect("/admin/clients")
    result = deactivate_client(db, client)
    _flash_mk(request, result, "Клиент деактивирован.")
    return _redirect("/admin/clients")


@router.post("/clients/{client_id}/block")
def client_block(request: Request, client_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    client = clients_service.get_client(db, client_id)
    if not client:
        flash(request, "Клиент не найден.", "danger")
        return _redirect("/admin/clients")
    result = block_client(db, client)
    _flash_mk(request, result, "Клиент заблокирован.")
    return _redirect("/admin/clients")


@router.post("/clients/{client_id}/delete")
def client_delete(request: Request, client_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    client = clients_service.get_client(db, client_id)
    if not client:
        flash(request, "Клиент не найден.", "danger")
        return _redirect("/admin/clients")
    if client.status == STATUS_ACTIVE:
        deactivate_client(db, client)
    clients_service.delete_client(db, client)
    flash(request, "Клиент удалён.", "info")
    return _redirect("/admin/clients")


def _flash_mk(request: Request, result: dict, ok_message: str) -> None:
    if result.get("error"):
        flash(request, f"{ok_message} Но MikroTik: {result['error']}", "warning")
    else:
        flash(request, ok_message, "success")


# ---------------------------------------------------------------------------
# Tariffs
# ---------------------------------------------------------------------------
@router.get("/tariffs")
def tariffs_list(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    return render(request, "admin_tariffs.html", tariffs=tariffs_service.list_tariffs(db))


@router.get("/tariffs/new")
def tariff_new(request: Request, admin=Depends(require_admin)):
    return render(request, "admin_tariff_form.html", tariff=None)


@router.post("/tariffs/new")
def tariff_create(
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    price: float = Form(0.0),
    currency: str = Form(settings.DEFAULT_CURRENCY),
    validity_days: int = Form(1),
    speed_limit: Optional[str] = Form(None),
    traffic_limit: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    tariffs_service.create_tariff(
        db,
        name=name,
        description=description,
        price=price,
        currency=currency,
        validity_days=validity_days,
        speed_limit=speed_limit,
        traffic_limit=traffic_limit,
        is_active=_bool(is_active),
    )
    flash(request, "Тариф создан.", "success")
    return _redirect("/admin/tariffs")


@router.get("/tariffs/{tariff_id}/edit")
def tariff_edit_form(request: Request, tariff_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    tariff = tariffs_service.get_tariff(db, tariff_id)
    if not tariff:
        flash(request, "Тариф не найден.", "danger")
        return _redirect("/admin/tariffs")
    return render(request, "admin_tariff_form.html", tariff=tariff)


@router.post("/tariffs/{tariff_id}/edit")
def tariff_edit(
    request: Request,
    tariff_id: int,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    price: float = Form(0.0),
    currency: str = Form(settings.DEFAULT_CURRENCY),
    validity_days: int = Form(1),
    speed_limit: Optional[str] = Form(None),
    traffic_limit: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    tariff = tariffs_service.get_tariff(db, tariff_id)
    if not tariff:
        flash(request, "Тариф не найден.", "danger")
        return _redirect("/admin/tariffs")
    tariffs_service.update_tariff(
        db,
        tariff,
        name=name,
        description=description,
        price=price,
        currency=currency,
        validity_days=validity_days,
        speed_limit=speed_limit,
        traffic_limit=traffic_limit,
        is_active=_bool(is_active),
    )
    flash(request, "Тариф обновлён.", "success")
    return _redirect("/admin/tariffs")


@router.post("/tariffs/{tariff_id}/delete")
def tariff_delete(request: Request, tariff_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    tariff = tariffs_service.get_tariff(db, tariff_id)
    if not tariff:
        flash(request, "Тариф не найден.", "danger")
        return _redirect("/admin/tariffs")
    tariffs_service.delete_tariff(db, tariff)
    flash(request, "Тариф удалён.", "info")
    return _redirect("/admin/tariffs")


# ---------------------------------------------------------------------------
# Payments / logs
# ---------------------------------------------------------------------------
@router.get("/payments")
def payments_list(
    request: Request,
    status: Optional[str] = None,
    phone: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    query = db.query(Payment).order_by(Payment.id.desc())
    if status:
        query = query.filter(Payment.status == status)
    if phone:
        ids = [c.id for c in db.query(Client).filter(Client.phone.ilike(f"%{phone}%")).all()]
        query = query.filter(Payment.client_id.in_(ids or [-1]))
    payments = query.limit(500).all()
    # Build a phone lookup for display.
    client_map = {c.id: c for c in db.query(Client).all()}
    return render(
        request,
        "admin_payments.html",
        payments=payments,
        client_map=client_map,
        status=status or "",
        phone=phone or "",
    )


@router.get("/payments.csv")
def payments_csv(
    request: Request,
    status: Optional[str] = None,
    phone: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    query = db.query(Payment).order_by(Payment.id.desc())
    if status:
        query = query.filter(Payment.status == status)
    if phone:
        ids = [c.id for c in db.query(Client).filter(Client.phone.ilike(f"%{phone}%")).all()]
        query = query.filter(Payment.client_id.in_(ids or [-1]))
    payments = query.all()
    client_map = {c.id: c for c in db.query(Client).all()}
    header = [
        "id", "client_id", "phone", "tariff_id", "amount", "currency",
        "provider", "provider_payment_id", "status", "created_at",
        "paid_at", "error_message",
    ]
    rows = [
        [
            p.id, p.client_id or "",
            client_map[p.client_id].phone if p.client_id in client_map else "",
            p.tariff_id or "", p.amount, p.currency, p.provider,
            p.provider_payment_id or "", p.status, _fmt_dt(p.created_at),
            _fmt_dt(p.paid_at), p.error_message or "",
        ]
        for p in payments
    ]
    return _csv_response("payments.csv", header, rows)


@router.get("/sms-logs")
def sms_logs(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    logs = db.query(SMSLog).order_by(SMSLog.id.desc()).limit(500).all()
    return render(request, "admin_sms_logs.html", logs=logs)


@router.get("/logs")
def access_logs(
    request: Request,
    action: Optional[str] = None,
    client_id: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    query = db.query(AccessLog).order_by(AccessLog.id.desc())
    if action:
        query = query.filter(AccessLog.action == action)
    if client_id:
        try:
            query = query.filter(AccessLog.client_id == int(client_id))
        except ValueError:
            pass
    logs = query.limit(500).all()
    actions = [r[0] for r in db.query(AccessLog.action).distinct().all()]
    return render(
        request,
        "admin_logs.html",
        logs=logs,
        actions=actions,
        action=action or "",
        client_id=client_id or "",
    )


# ---------------------------------------------------------------------------
# Sync / settings
# ---------------------------------------------------------------------------
@router.get("/sync")
def sync_page(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    return render(request, "admin_sync.html", result=None, device=get_active_device(db))


@router.post("/sync")
def sync_run(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    result = sync_with_mikrotik(db)
    return render(request, "admin_sync.html", result=result, device=get_active_device(db))


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    device = get_active_device(db)
    # Hide password in DATABASE_URL.
    safe_db_url = settings.DATABASE_URL
    if "@" in safe_db_url and "//" in safe_db_url:
        scheme, rest = safe_db_url.split("//", 1)
        if "@" in rest:
            creds, host = rest.split("@", 1)
            user = creds.split(":", 1)[0]
            safe_db_url = f"{scheme}//{user}:***@{host}"

    db_status = "ok"
    try:
        from sqlalchemy import text

        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "error"

    mk_status = "not_configured"
    if device is not None:
        mk_client = build_client(device)
        res = mk_client.check_connection()
        mk_status = "ok" if res.get("success") else "error"

    info = {
        "app_name": settings.APP_NAME,
        "app_version": settings.APP_VERSION,
        "database_url": safe_db_url,
        "database_status": db_status,
        "active_mikrotik": device.name if device else None,
        "mikrotik_status": mk_status,
        "allowed_list": settings.DEFAULT_ALLOWED_LIST,
        "guest_network": settings.DEFAULT_GUEST_NETWORK,
        "sms_provider": settings_store.effective(db)["SMS_PROVIDER"],
        "payment_provider": settings_store.effective(db)["PAYMENT_PROVIDER"],
    }
    return render(request, "admin_settings.html", info=info)


# ---------------------------------------------------------------------------
# Integrations (SMS / payment providers) — configured from the UI
# ---------------------------------------------------------------------------
@router.get("/integrations")
def integrations(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    cfg = settings_store.effective(db)
    secret_set = {k: bool(cfg.get(k)) for k in settings_store.SECRET_KEYS}
    return render(
        request,
        "admin_integrations.html",
        cfg=cfg,
        secret_set=secret_set,
        sms_json_body=settings_store.as_bool(cfg.get("SMS_JSON_BODY", "true")),
    )


@router.post("/integrations/sms")
def integrations_sms(
    request: Request,
    SMS_PROVIDER: str = Form("mock"),
    SMS_API_URL: str = Form(""),
    SMS_API_KEY: str = Form(""),
    SMS_API_METHOD: str = Form("POST"),
    SMS_API_AUTH_HEADER: str = Form("Authorization"),
    SMS_API_AUTH_PREFIX: str = Form("Bearer"),
    SMS_SENDER: str = Form(""),
    SMS_PHONE_PARAM: str = Form("phone"),
    SMS_TEXT_PARAM: str = Form("text"),
    SMS_SENDER_PARAM: str = Form("from"),
    SMS_EXTRA_PARAMS: str = Form(""),
    SMS_JSON_BODY: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    data = {
        "SMS_PROVIDER": SMS_PROVIDER,
        "SMS_API_URL": SMS_API_URL.strip(),
        "SMS_API_METHOD": SMS_API_METHOD,
        "SMS_API_AUTH_HEADER": SMS_API_AUTH_HEADER,
        "SMS_API_AUTH_PREFIX": SMS_API_AUTH_PREFIX,
        "SMS_SENDER": SMS_SENDER,
        "SMS_PHONE_PARAM": SMS_PHONE_PARAM,
        "SMS_TEXT_PARAM": SMS_TEXT_PARAM,
        "SMS_SENDER_PARAM": SMS_SENDER_PARAM,
        "SMS_EXTRA_PARAMS": SMS_EXTRA_PARAMS,
        "SMS_JSON_BODY": "true" if _bool(SMS_JSON_BODY) else "false",
    }
    # Empty key field keeps the previously stored key.
    if SMS_API_KEY.strip():
        data["SMS_API_KEY"] = SMS_API_KEY.strip()
    settings_store.save(db, data)
    flash(request, "Настройки SMS сохранены.", "success")
    return _redirect("/admin/integrations")


@router.post("/integrations/payment")
def integrations_payment(
    request: Request,
    PAYMENT_PROVIDER: str = Form("mock"),
    PAYMENT_API_URL: str = Form(""),
    PAYMENT_API_KEY: str = Form(""),
    PAYMENT_API_AUTH_HEADER: str = Form("Authorization"),
    PAYMENT_API_AUTH_PREFIX: str = Form("Bearer"),
    PAYMENT_RETURN_URL: str = Form(""),
    PAYMENT_CALLBACK_URL: str = Form(""),
    PAYMENT_PAY_URL_FIELD: str = Form("payment_url"),
    PAYMENT_ID_FIELD: str = Form("id"),
    PUBLIC_BASE_URL: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    data = {
        "PAYMENT_PROVIDER": PAYMENT_PROVIDER,
        "PAYMENT_API_URL": PAYMENT_API_URL.strip(),
        "PAYMENT_API_AUTH_HEADER": PAYMENT_API_AUTH_HEADER,
        "PAYMENT_API_AUTH_PREFIX": PAYMENT_API_AUTH_PREFIX,
        "PAYMENT_RETURN_URL": PAYMENT_RETURN_URL.strip(),
        "PAYMENT_CALLBACK_URL": PAYMENT_CALLBACK_URL.strip(),
        "PAYMENT_PAY_URL_FIELD": PAYMENT_PAY_URL_FIELD,
        "PAYMENT_ID_FIELD": PAYMENT_ID_FIELD,
        "PUBLIC_BASE_URL": PUBLIC_BASE_URL.strip(),
    }
    if PAYMENT_API_KEY.strip():
        data["PAYMENT_API_KEY"] = PAYMENT_API_KEY.strip()
    settings_store.save(db, data)
    flash(request, "Настройки оплаты сохранены.", "success")
    return _redirect("/admin/integrations")


@router.post("/integrations/test-sms")
def integrations_test_sms(
    request: Request,
    phone: str = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    res = sms_service.send_sms(db, phone.strip(), f"Тест SMS от {settings.APP_NAME}")
    if res.get("success"):
        flash(request, "Тестовая SMS отправлена (см. SMS / OTP логи).", "success")
    else:
        flash(request, f"Ошибка отправки SMS: {res.get('error')}", "danger")
    return _redirect("/admin/integrations")
