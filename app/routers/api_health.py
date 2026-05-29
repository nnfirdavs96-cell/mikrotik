"""Public health endpoint (no API key required)."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..mikrotik.service import build_client, get_active_device

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        database = "error"

    mikrotik = "not_configured"
    device = get_active_device(db)
    if device is not None:
        client = build_client(device)
        result = client.check_connection()
        mikrotik = "ok" if result.get("success") else "error"

    return {"api": "ok", "database": database, "mikrotik": mikrotik}
