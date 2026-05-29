"""MikroTik device CRUD + active-device management."""
from typing import Optional

from sqlalchemy.orm import Session

from .. import models
from ..mikrotik.service import test_device_connection
from .logs import log_access


def list_devices(db: Session):
    return db.query(models.MikroTikDevice).order_by(models.MikroTikDevice.id.asc()).all()


def get_device(db: Session, device_id: int) -> Optional[models.MikroTikDevice]:
    return (
        db.query(models.MikroTikDevice)
        .filter(models.MikroTikDevice.id == device_id)
        .first()
    )


def _unset_other_active(db: Session, keep_id: Optional[int] = None) -> None:
    query = db.query(models.MikroTikDevice).filter(
        models.MikroTikDevice.is_active.is_(True)
    )
    if keep_id is not None:
        query = query.filter(models.MikroTikDevice.id != keep_id)
    query.update({models.MikroTikDevice.is_active: False}, synchronize_session=False)


def create_device(db: Session, **data) -> models.MikroTikDevice:
    # For the MVP only one device may be active at a time.
    if data.get("is_active"):
        _unset_other_active(db)
    device = models.MikroTikDevice(**data)
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def update_device(db: Session, device: models.MikroTikDevice, **data) -> models.MikroTikDevice:
    # If password is empty/None, keep the existing one.
    if "password" in data and not data["password"]:
        data.pop("password")
    if data.get("is_active"):
        _unset_other_active(db, keep_id=device.id)
    for key, value in data.items():
        setattr(device, key, value)
    db.commit()
    db.refresh(device)
    return device


def set_active(db: Session, device: models.MikroTikDevice) -> models.MikroTikDevice:
    _unset_other_active(db, keep_id=device.id)
    device.is_active = True
    db.commit()
    db.refresh(device)
    return device


def delete_device(db: Session, device: models.MikroTikDevice) -> None:
    db.delete(device)
    db.commit()


def test_connection(db: Session, device: models.MikroTikDevice) -> dict:
    result = test_device_connection(db, device)
    log_access(
        db,
        action="mikrotik_test",
        mikrotik_id=device.id,
        mikrotik_result="ok" if result.get("success") else None,
        error_message=None if result.get("success") else (
            result.get("details") or result.get("message")
        ),
    )
    return result
