"""Synchronise the database with the MikroTik allowed_clients list."""
import datetime as dt

from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..mikrotik.client import MikroTikError
from ..mikrotik.service import build_client, get_active_device
from .logs import log_access


def refresh_connected(db: Session) -> dict:
    """Update known clients' IP/hostname/last_seen from current DHCP leases.

    Merges by MAC: for each lease with a MAC that matches a client, refresh its
    current_ip / hostname / last_seen. Used by the periodic scheduler and the
    Refresh button.
    """
    device = get_active_device(db)
    if device is None:
        return {"success": False, "message": "No active MikroTik device configured"}

    mk_client = build_client(device)
    try:
        leases = mk_client.get_dhcp_leases()
    except MikroTikError as exc:
        return {"success": False, "message": "MikroTik API connection failed",
                "details": str(exc)}
    finally:
        mk_client.close()

    now = dt.datetime.utcnow()
    updated = 0
    for lease in leases:
        mac = lease.get("mac_address")
        if not mac:
            continue
        client = (
            db.query(models.Client)
            .filter(models.Client.mac_address.ilike(mac))
            .first()
        )
        if client is None:
            continue
        if lease.get("address"):
            client.ip_address = lease["address"]
        if lease.get("hostname"):
            client.hostname = lease["hostname"]
        client.last_seen = now
        updated += 1
    db.commit()
    return {"success": True, "updated": updated, "leases": len(leases)}


def sync_with_mikrotik(db: Session) -> dict:
    """Make allowed_clients match the set of status=active clients.

    Active clients (status=1) must be present; everyone else must be absent.
    """
    device = get_active_device(db)
    if device is None:
        return {"success": False, "message": "No active MikroTik device configured"}

    active_clients = (
        db.query(models.Client)
        .filter(
            models.Client.status == models.STATUS_ACTIVE,
            models.Client.ip_address.isnot(None),
        )
        .all()
    )
    payload = [
        {
            "ip": c.ip_address,
            "phone": c.phone,
            "mac": c.mac_address,
            "client_id": c.id,
        }
        for c in active_clients
    ]

    mk_client = build_client(device)
    try:
        result = mk_client.sync_allowed_clients(payload, settings.DEFAULT_ALLOWED_LIST)
        log_access(
            db,
            action="sync",
            mikrotik_id=device.id,
            mikrotik_result=(
                f"added={result['added']} removed={result['removed']} "
                f"already={result['already']} errors={len(result['errors'])}"
            ),
            error_message="; ".join(result["errors"]) or None,
        )
        return {"success": True, **result}
    except MikroTikError as exc:
        log_access(db, action="sync", mikrotik_id=device.id, error_message=str(exc))
        return {
            "success": False,
            "message": "MikroTik API connection failed",
            "details": str(exc),
        }
    finally:
        mk_client.close()
