"""Portal helpers: determine the client's device from its IP via DHCP lease."""
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from ..config import settings
from ..mikrotik.client import MikroTikError
from ..mikrotik.service import build_client, get_active_device


def get_client_ip(request: Request) -> Optional[str]:
    """Resolve the client IP, honouring a reverse proxy X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def resolve_device_info(db: Session, ip_address: Optional[str]) -> dict:
    """Look up the DHCP lease for ``ip_address`` on the active MikroTik.

    Returns a dict:
        {ip, mac, hostname, mikrotik_id, found, message}

    The portal never crashes: if the router is offline or no lease matches we
    return found=False with a human-readable message. Whether that blocks the
    flow is decided by the PORTAL_REQUIRE_LEASE setting.
    """
    info = {
        "ip": None,            # client IP — set ONLY when a real lease is found
        "mac": None,
        "hostname": None,
        "mikrotik_id": None,
        "found": False,
        "message": None,
        "request_ip": ip_address,  # raw IP seen by the server (for logging)
    }

    device = get_active_device(db)
    if device is None:
        info["message"] = "No active MikroTik device configured"
        return info
    info["mikrotik_id"] = device.id

    if not ip_address:
        info["message"] = "Could not determine client IP address"
        return info

    # CRITICAL: the request IP must be the client's, never the router's. If we
    # see the MikroTik's own IP, traffic guest->portal is being masqueraded.
    # Do NOT store it as the client IP — ask to bind the device manually.
    if ip_address == device.host:
        info["message"] = (
            "Виден IP роутера, а не клиента. Уберите masquerade для трафика "
            "гость→портал (или используйте Hotspot). Устройство можно привязать "
            "вручную из списка DHCP leases в админке."
        )
        return info

    mk_client = build_client(device)
    try:
        lease = mk_client.find_lease_by_ip(ip_address)
        if lease:
            info["ip"] = lease.get("address") or ip_address
            info["mac"] = lease.get("mac_address")
            info["hostname"] = lease.get("hostname")
            info["found"] = True
        else:
            # Fallback: try the hotspot host table (when a Hotspot is used).
            mac = None
            try:
                host = mk_client.find_hotspot_host_by_ip(ip_address)
                mac = host.get("mac_address") if host else None
            except MikroTikError:
                mac = None  # hotspot not configured / unavailable — ignore
            if mac:
                info["ip"] = ip_address
                info["mac"] = mac
                info["found"] = True
            else:
                info["message"] = (
                    "Не удалось определить устройство. Переподключитесь к Wi-Fi и "
                    "попробуйте снова."
                )
    except MikroTikError as exc:
        info["message"] = f"MikroTik API connection failed: {exc}"
    finally:
        mk_client.close()

    return info


def lease_required() -> bool:
    return bool(settings.PORTAL_REQUIRE_LEASE)
