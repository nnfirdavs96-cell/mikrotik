"""REST API for MikroTik devices. All endpoints require X-API-Key."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_api_key
from ..mikrotik.service import build_client, get_capsman_for_device, get_hotspot_for_device
from ..schemas import MikroTikCreate, MikroTikOut
from ..services import clients as clients_service
from ..services import mikrotik_devices as devices_service

router = APIRouter(prefix="/api/mikrotik", tags=["mikrotik"], dependencies=[Depends(require_api_key)])


def _get_or_404(db: Session, device_id: int):
    device = devices_service.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=404, detail={"success": False, "message": "MikroTik device not found"})
    return device


@router.get("", response_model=List[MikroTikOut])
def list_devices(db: Session = Depends(get_db)):
    return devices_service.list_devices(db)


@router.post("", response_model=MikroTikOut)
def create_device(payload: MikroTikCreate, db: Session = Depends(get_db)):
    return devices_service.create_device(db, **payload.model_dump())


@router.post("/{device_id}/test")
def test_device(device_id: int, db: Session = Depends(get_db)):
    device = _get_or_404(db, device_id)
    return devices_service.test_connection(db, device)


@router.get("/{device_id}/dhcp-leases")
def dhcp_leases(device_id: int, db: Session = Depends(get_db)):
    device = _get_or_404(db, device_id)
    client = build_client(device)
    try:
        leases = client.get_dhcp_leases()
        return {"success": True, "leases": leases}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "message": "MikroTik API connection failed", "details": str(exc)}
    finally:
        client.close()


@router.get("/{device_id}/connected-clients")
def connected_clients(device_id: int, db: Session = Depends(get_db)):
    device = _get_or_404(db, device_id)
    client = build_client(device)
    try:
        leases = client.get_dhcp_leases()
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "message": "MikroTik API connection failed", "details": str(exc)}
    finally:
        client.close()

    enriched = []
    for lease in leases:
        registered = None
        if lease.get("mac_address"):
            registered = clients_service.get_client_by_mac(db, lease["mac_address"])
        enriched.append(
            {
                **lease,
                "registered": registered is not None,
                "client_id": registered.id if registered else None,
                "client_status": registered.status if registered else None,
            }
        )
    return {"success": True, "clients": enriched}


@router.get("/{device_id}/capsman")
def capsman(device_id: int, db: Session = Depends(get_db)):
    device = _get_or_404(db, device_id)
    return get_capsman_for_device(device)


@router.get("/{device_id}/hotspot-hosts")
def hotspot(device_id: int, db: Session = Depends(get_db)):
    device = _get_or_404(db, device_id)
    return get_hotspot_for_device(device)
