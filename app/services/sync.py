"""Synchronise the database with the MikroTik allowed_clients list."""
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..mikrotik.client import MikroTikError
from ..mikrotik.service import build_client, get_active_device
from .logs import log_access


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
