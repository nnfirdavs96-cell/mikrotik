"""REST API for client management. All endpoints require X-API-Key."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_api_key
from ..models import STATUS_ACTIVE
from ..schemas import ClientOut, ClientUpdate
from ..services import clients as clients_service
from ..services.access_control import (
    activate_client,
    block_client,
    deactivate_client,
)
from ..services.logs import log_access

router = APIRouter(prefix="/api/clients", tags=["clients"], dependencies=[Depends(require_api_key)])


def _get_or_404(db: Session, client_id: int):
    client = clients_service.get_client(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Client not found"})
    return client


@router.get("", response_model=List[ClientOut])
def list_clients(
    q: Optional[str] = None,
    status: Optional[int] = None,
    db: Session = Depends(get_db),
):
    return clients_service.search_clients(db, query=q, status=status)


@router.get("/{client_id}", response_model=ClientOut)
def get_one(client_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, client_id)


@router.put("/{client_id}", response_model=ClientOut)
def update_one(client_id: int, payload: ClientUpdate, db: Session = Depends(get_db)):
    client = _get_or_404(db, client_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(client, key, value)
    db.commit()
    db.refresh(client)
    log_access(db, action="update_client", client_id=client.id, new_status=client.status)
    return client


@router.delete("/{client_id}")
def delete_one(client_id: int, db: Session = Depends(get_db)):
    client = _get_or_404(db, client_id)
    # If the client is active, remove its IP from MikroTik first.
    if client.status == STATUS_ACTIVE:
        deactivate_client(db, client)
    clients_service.delete_client(db, client)
    return {"success": True, "message": "Client deleted"}


@router.post("/{client_id}/activate")
def activate(client_id: int, db: Session = Depends(get_db)):
    client = _get_or_404(db, client_id)
    return activate_client(db, client)


@router.post("/{client_id}/deactivate")
def deactivate(client_id: int, db: Session = Depends(get_db)):
    client = _get_or_404(db, client_id)
    return deactivate_client(db, client)


@router.post("/{client_id}/block")
def block(client_id: int, db: Session = Depends(get_db)):
    client = _get_or_404(db, client_id)
    return block_client(db, client)


@router.post("/by-mac/{mac_address}/activate")
def activate_by_mac(mac_address: str, db: Session = Depends(get_db)):
    client = clients_service.get_client_by_mac(db, mac_address)
    if not client:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Client not found by MAC"})
    return activate_client(db, client)


@router.post("/by-mac/{mac_address}/deactivate")
def deactivate_by_mac(mac_address: str, db: Session = Depends(get_db)):
    client = clients_service.get_client_by_mac(db, mac_address)
    if not client:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Client not found by MAC"})
    return deactivate_client(db, client)
