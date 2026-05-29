"""REST API: maintenance tasks. Requires X-API-Key."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_api_key
from ..services.expire import expire_clients

router = APIRouter(prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(require_api_key)])


@router.post("/expire-clients")
def run_expire_clients(db: Session = Depends(get_db)):
    return expire_clients(db)
