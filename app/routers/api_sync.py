"""REST API: synchronise the DB with MikroTik. Requires X-API-Key."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_api_key
from ..services.sync import sync_with_mikrotik

router = APIRouter(prefix="/api/sync", tags=["sync"], dependencies=[Depends(require_api_key)])


@router.post("/mikrotik")
def sync_mikrotik(db: Session = Depends(get_db)):
    return sync_with_mikrotik(db)
