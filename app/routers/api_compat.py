"""Compatibility REST endpoints matching the spec's naming.

These complement the existing routers with the exact paths requested in the
audit spec. All require X-API-Key.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_api_key
from ..mikrotik.client import MikroTikError
from ..mikrotik.service import build_client, get_active_device
from ..schemas import BindDevice
from ..services import clients as clients_service
from ..services import mikrotik_devices as devices_service
from ..services.sync import sync_with_mikrotik

router = APIRouter(prefix="/api", tags=["compat"], dependencies=[Depends(require_api_key)])


@router.get("/connected-clients")
def connected_clients(db: Session = Depends(get_db)):
    """Connected devices (DHCP leases) on the active MikroTik, enriched."""
    device = get_active_device(db)
    if device is None:
        return {"success": False, "message": "No active MikroTik device", "clients": []}
    client = build_client(device)
    try:
        leases = client.get_dhcp_leases()
    except MikroTikError as exc:
        return {"success": False, "message": "MikroTik API connection failed",
                "details": str(exc), "clients": []}
    finally:
        client.close()

    enriched = []
    for lease in leases:
        reg = (
            clients_service.get_client_by_mac(db, lease["mac_address"])
            if lease.get("mac_address")
            else None
        )
        enriched.append(
            {
                **lease,
                "registered": reg is not None,
                "client_id": reg.id if reg else None,
                "client_status": reg.status if reg else None,
            }
        )
    return {"success": True, "clients": enriched}


@router.post("/clients/{client_id}/bind-device")
def bind_device(client_id: int, payload: BindDevice, db: Session = Depends(get_db)):
    """Attach a device (MAC/IP/hostname) to a client."""
    client = clients_service.get_client(db, client_id)
    if not client:
        raise HTTPException(404, detail={"success": False, "message": "Client not found"})
    clients_service.bind_device(
        db,
        client,
        mac_address=payload.mac_address,
        ip_address=payload.ip_address,
        hostname=payload.hostname,
    )
    return {"success": True, "message": "Device bound", "client_id": client.id}


@router.post("/sync/mikrotik/{device_id}")
def sync_mikrotik_device(device_id: int, db: Session = Depends(get_db)):
    """Sync allowed_clients for the given device (alias of /api/sync/mikrotik)."""
    device = devices_service.get_device(db, device_id)
    if not device:
        raise HTTPException(404, detail={"success": False, "message": "Device not found"})
    return sync_with_mikrotik(db)
