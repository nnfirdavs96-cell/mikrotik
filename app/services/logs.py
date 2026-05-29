"""Access-log helpers."""
from typing import Optional

from sqlalchemy.orm import Session

from .. import models


def log_access(
    db: Session,
    action: str,
    client_id: Optional[int] = None,
    mikrotik_id: Optional[int] = None,
    old_status: Optional[int] = None,
    new_status: Optional[int] = None,
    mikrotik_result: Optional[str] = None,
    error_message: Optional[str] = None,
) -> models.AccessLog:
    entry = models.AccessLog(
        action=action,
        client_id=client_id,
        mikrotik_id=mikrotik_id,
        old_status=old_status,
        new_status=new_status,
        mikrotik_result=mikrotik_result,
        error_message=error_message,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def recent_logs(db: Session, limit: int = 10):
    return (
        db.query(models.AccessLog)
        .order_by(models.AccessLog.created_at.desc())
        .limit(limit)
        .all()
    )
