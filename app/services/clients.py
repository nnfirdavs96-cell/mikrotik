"""Client queries and helpers."""
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from .logs import log_access


def get_client(db: Session, client_id: int) -> Optional[models.Client]:
    return db.query(models.Client).filter(models.Client.id == client_id).first()


def get_client_by_mac(db: Session, mac_address: str) -> Optional[models.Client]:
    return (
        db.query(models.Client)
        .filter(models.Client.mac_address.ilike(mac_address))
        .order_by(models.Client.id.desc())
        .first()
    )


def get_client_by_phone(db: Session, phone: str) -> Optional[models.Client]:
    return (
        db.query(models.Client)
        .filter(models.Client.phone == phone)
        .order_by(models.Client.id.desc())
        .first()
    )


def get_client_by_ip(db: Session, ip_address: str) -> Optional[models.Client]:
    return (
        db.query(models.Client)
        .filter(models.Client.ip_address == ip_address)
        .order_by(models.Client.id.desc())
        .first()
    )


def search_clients(
    db: Session,
    query: Optional[str] = None,
    status: Optional[int] = None,
):
    q = db.query(models.Client)
    if query:
        like = f"%{query}%"
        q = q.filter(
            or_(
                models.Client.phone.ilike(like),
                models.Client.mac_address.ilike(like),
                models.Client.ip_address.ilike(like),
            )
        )
    if status is not None:
        q = q.filter(models.Client.status == status)
    return q.order_by(models.Client.id.desc()).all()


def upsert_registration(
    db: Session,
    phone: str,
    ip_address: Optional[str],
    mac_address: Optional[str],
    hostname: Optional[str],
    mikrotik_id: Optional[int],
) -> models.Client:
    """Find an existing client by MAC (or phone) or create a new one.

    Used by the captive portal when the client submits their phone number.
    """
    client = None
    if mac_address:
        client = get_client_by_mac(db, mac_address)
    if client is None:
        client = get_client_by_phone(db, phone)

    if client is None:
        client = models.Client(phone=phone)
        db.add(client)

    client.phone = phone
    if ip_address:
        client.ip_address = ip_address
    if mac_address:
        client.mac_address = mac_address
    if hostname:
        client.hostname = hostname
    if mikrotik_id:
        client.mikrotik_id = mikrotik_id

    db.commit()
    db.refresh(client)
    return client


def delete_client(db: Session, client: models.Client) -> None:
    log_access(
        db,
        action="delete_client",
        client_id=client.id,
        mikrotik_id=client.mikrotik_id,
        old_status=client.status,
    )
    db.delete(client)
    db.commit()
