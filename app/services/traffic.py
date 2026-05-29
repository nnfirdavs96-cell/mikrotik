"""Traffic-quota enforcement based on MikroTik simple-queue byte counters."""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..mikrotik.client import MikroTikError
from ..mikrotik.service import build_client, get_active_device
from .access_control import deactivate_client

logger = logging.getLogger("wam.traffic")

_UNITS = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}


def parse_size(text: Optional[str]) -> Optional[int]:
    """Parse '5GB', '500M', '1024k', '1000000' into a number of bytes."""
    if not text:
        return None
    s = str(text).strip().lower().replace("ib", "").replace("b", "").replace(" ", "")
    if not s:
        return None
    mult = 1
    if s[-1] in _UNITS:
        mult = _UNITS[s[-1]]
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def enforce_traffic_quotas(db: Session) -> dict:
    """Deactivate active clients that exceeded their tariff traffic_limit."""
    device = get_active_device(db)
    if device is None:
        return {"success": False, "message": "No active MikroTik device"}

    clients = (
        db.query(models.Client)
        .filter(models.Client.status == models.STATUS_ACTIVE)
        .all()
    )
    result = {"success": True, "checked": 0, "disabled": 0, "errors": []}

    mk = build_client(device)
    try:
        for client in clients:
            limit = parse_size(client.tariff.traffic_limit) if client.tariff else None
            if not limit or not client.ip_address:
                continue
            result["checked"] += 1
            qname = f"{settings.QUEUE_PREFIX}-{client.id}"
            try:
                used = mk.get_simple_queue_bytes(qname)
            except MikroTikError as exc:
                result["errors"].append(f"client {client.id}: {exc}")
                continue
            if used is not None and used >= limit:
                deactivate_client(
                    db,
                    client,
                    set_status=models.STATUS_EXPIRED,
                    action="traffic_limit",
                )
                result["disabled"] += 1
                logger.info(
                    "client %s exceeded traffic limit (%s/%s bytes)",
                    client.id, used, limit,
                )
    except MikroTikError as exc:
        result["success"] = False
        result["errors"].append(str(exc))
    finally:
        mk.close()
    return result
