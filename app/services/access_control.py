"""Core access control: activate / deactivate / block clients.

Each operation updates the MikroTik allowed_clients address-list (when a router
is configured and reachable), updates the client record and writes an
access_logs entry. MikroTik failures are captured, never raised, so the web UI
and API keep working even when the router is offline.
"""
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..mikrotik.client import MikroTikError
from ..mikrotik.service import build_client, get_active_device
from ..models import (
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    STATUS_INACTIVE,
    Client,
    utcnow,
)
from .logs import log_access


def activate_client(db: Session, client: Client, reason: str = "manual") -> dict:
    """Set client active and add its IP to allowed_clients."""
    old_status = client.status
    device = get_active_device(db)

    mk_ok = False
    mk_result: Optional[str] = None
    mk_error: Optional[str] = None

    if not client.ip_address:
        mk_error = "Client has no IP address (no DHCP lease yet)"
    elif device is None:
        mk_error = "No active MikroTik device configured"
    elif client.ip_address == device.host:
        mk_error = (
            "IP клиента совпадает с IP роутера — привяжите устройство из DHCP "
            "leases (см. редактирование клиента)"
        )
    else:
        mk_client = build_client(device)
        try:
            res = mk_client.add_ip_to_allowed_list(
                client.ip_address,
                client.phone,
                client.mac_address,
                client.id,
                settings.DEFAULT_ALLOWED_LIST,
            )
            mk_ok = True
            mk_result = res.get("message")
            # Stage 2: apply per-tariff speed limit via a simple queue.
            if (
                settings.APPLY_QUEUES
                and client.tariff is not None
                and client.tariff.speed_limit
            ):
                qname = f"{settings.QUEUE_PREFIX}-{client.id}"
                qcomment = f"wifi-client client_id={client.id} phone={client.phone}"
                qres = mk_client.add_simple_queue(
                    qname, client.ip_address, client.tariff.speed_limit, qcomment
                )
                mk_result = f"{mk_result}; queue: {qres.get('message')}"
        except MikroTikError as exc:
            mk_error = str(exc)
        finally:
            mk_client.close()

    client.status = STATUS_ACTIVE
    client.activated_at = utcnow()
    client.deactivated_at = None
    if device is not None:
        client.mikrotik_id = device.id
    db.commit()

    action = "activate_after_payment" if reason == "payment" else "activate"
    log_access(
        db,
        action=action,
        client_id=client.id,
        mikrotik_id=device.id if device else None,
        old_status=old_status,
        new_status=STATUS_ACTIVE,
        mikrotik_result=mk_result,
        error_message=mk_error,
    )
    return {
        "success": True,
        "mikrotik_ok": mk_ok,
        "message": mk_result or mk_error or "Client activated",
        "error": mk_error,
    }


def deactivate_client(
    db: Session,
    client: Client,
    set_status: int = STATUS_INACTIVE,
    action: str = "deactivate",
) -> dict:
    """Remove client IP from allowed_clients and set its status."""
    old_status = client.status
    device = get_active_device(db)

    mk_ok = False
    mk_result: Optional[str] = None
    mk_error: Optional[str] = None

    if device is None:
        mk_error = "No active MikroTik device configured"
    else:
        mk_client = build_client(device)
        try:
            # Remove by client_id (robust even if the IP changed)...
            res = mk_client.remove_allowed_by_client_id(
                client.id, settings.DEFAULT_ALLOWED_LIST
            )
            removed = res.get("removed", 0)
            # ...and also by current IP as a safety net (skip the router IP).
            if client.ip_address and client.ip_address != device.host:
                mk_client.remove_ip_from_allowed_list(
                    client.ip_address, settings.DEFAULT_ALLOWED_LIST
                )
            mk_ok = True
            mk_result = f"removed {removed} address-list entry(ies)"
            # Stage 2: remove the per-client speed-limit queue.
            if settings.APPLY_QUEUES:
                mk_client.remove_simple_queue(f"{settings.QUEUE_PREFIX}-{client.id}")
        except MikroTikError as exc:
            mk_error = str(exc)
        finally:
            mk_client.close()

    client.status = set_status
    client.deactivated_at = utcnow()
    db.commit()

    log_access(
        db,
        action=action,
        client_id=client.id,
        mikrotik_id=device.id if device else None,
        old_status=old_status,
        new_status=set_status,
        mikrotik_result=mk_result,
        error_message=mk_error,
    )
    return {
        "success": True,
        "mikrotik_ok": mk_ok,
        "message": mk_result or mk_error or "Client deactivated",
        "error": mk_error,
    }


def block_client(db: Session, client: Client) -> dict:
    """Block a client (status=4) and remove it from allowed_clients."""
    return deactivate_client(
        db, client, set_status=STATUS_BLOCKED, action="block"
    )
