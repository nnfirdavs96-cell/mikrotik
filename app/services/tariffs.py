"""Tariff CRUD and seeding."""
from typing import Optional

from sqlalchemy.orm import Session

from .. import models
from ..config import settings


def list_tariffs(db: Session, only_active: bool = False):
    query = db.query(models.Tariff)
    if only_active:
        query = query.filter(models.Tariff.is_active.is_(True))
    return query.order_by(models.Tariff.price.asc()).all()


def get_tariff(db: Session, tariff_id: int) -> Optional[models.Tariff]:
    return db.query(models.Tariff).filter(models.Tariff.id == tariff_id).first()


def create_tariff(db: Session, **data) -> models.Tariff:
    tariff = models.Tariff(**data)
    db.add(tariff)
    db.commit()
    db.refresh(tariff)
    return tariff


def update_tariff(db: Session, tariff: models.Tariff, **data) -> models.Tariff:
    for key, value in data.items():
        setattr(tariff, key, value)
    db.commit()
    db.refresh(tariff)
    return tariff


def delete_tariff(db: Session, tariff: models.Tariff) -> None:
    db.delete(tariff)
    db.commit()


def seed_default_tariffs(db: Session) -> None:
    """Create a few example tariffs on first run (if none exist)."""
    if db.query(models.Tariff).count() > 0:
        return
    currency = settings.DEFAULT_CURRENCY
    defaults = [
        dict(name="1 день", description="Доступ на 24 часа", price=5.0,
             currency=currency, validity_days=1, is_active=True),
        dict(name="7 дней", description="Доступ на неделю", price=25.0,
             currency=currency, validity_days=7, is_active=True),
        dict(name="30 дней", description="Доступ на месяц", price=80.0,
             currency=currency, validity_days=30, is_active=True),
    ]
    for data in defaults:
        db.add(models.Tariff(**data))
    db.commit()
