"""High-level MikroTik operations bound to database device records.

This layer turns a ``MikroTikDevice`` row into a connected client, performs an
operation and translates failures into structured results so the rest of the
application never crashes when the router is offline.
"""
from typing import Optional

from sqlalchemy.orm import Session

from ..models import MikroTikDevice, utcnow
from .client import MikroTikAPIClient, MikroTikError


def build_client(device: MikroTikDevice) -> MikroTikAPIClient:
    return MikroTikAPIClient(
        host=device.host,
        username=device.username,
        password=device.password,
        port=device.port,
        use_ssl=device.use_ssl,
    )


def get_active_device(db: Session) -> Optional[MikroTikDevice]:
    return (
        db.query(MikroTikDevice)
        .filter(MikroTikDevice.is_active.is_(True))
        .order_by(MikroTikDevice.id.asc())
        .first()
    )


def test_device_connection(db: Session, device: MikroTikDevice) -> dict:
    """Run check_connection() and persist last_status / last_error."""
    client = build_client(device)
    result = client.check_connection()

    device.last_checked_at = utcnow()
    device.last_status = "ok" if result.get("success") else "error"
    device.last_error = (
        None if result.get("success") else (result.get("details") or result.get("message"))
    )
    db.commit()
    return result


def get_leases_for_device(device: MikroTikDevice) -> dict:
    """Fetch DHCP leases, returning a structured success/error dict."""
    client = build_client(device)
    try:
        leases = client.get_dhcp_leases()
        return {"success": True, "leases": leases}
    except MikroTikError as exc:
        return {
            "success": False,
            "message": "MikroTik API connection failed",
            "details": str(exc),
            "leases": [],
        }
    finally:
        client.close()


def get_hotspot_for_device(device: MikroTikDevice) -> dict:
    """Fetch hotspot hosts + active sessions as a structured dict."""
    client = build_client(device)
    try:
        return {
            "success": True,
            "hosts": client.get_hotspot_hosts(),
            "active": client.get_hotspot_active(),
        }
    except MikroTikError as exc:
        return {
            "success": False,
            "message": "MikroTik API connection failed",
            "details": str(exc),
            "hosts": [],
            "active": [],
        }
    finally:
        client.close()


def get_capsman_for_device(device: MikroTikDevice) -> dict:
    """Fetch CAPsMAN info (APs + connected clients) as a structured dict."""
    client = build_client(device)
    try:
        data = client.get_capsman_info()
        return {"success": True, **data}
    except MikroTikError as exc:
        return {
            "success": False,
            "message": "MikroTik API connection failed",
            "details": str(exc),
            "stack": None,
            "caps": [],
            "clients": [],
        }
    finally:
        client.close()
