"""Expire clients whose tariff validity has ended."""
from sqlalchemy.orm import Session

from .. import models
from ..models import utcnow
from .access_control import deactivate_client


def expire_clients(db: Session) -> dict:
    """Deactivate active clients whose expires_at is in the past."""
    now = utcnow()
    clients = (
        db.query(models.Client)
        .filter(
            models.Client.status == models.STATUS_ACTIVE,
            models.Client.expires_at.isnot(None),
            models.Client.expires_at < now,
        )
        .all()
    )

    result = {"success": True, "expired": 0, "errors": []}
    for client in clients:
        res = deactivate_client(
            db,
            client,
            set_status=models.STATUS_EXPIRED,
            action="expire_client",
        )
        result["expired"] += 1
        if res.get("error"):
            result["errors"].append(f"client {client.id}: {res['error']}")
    return result
