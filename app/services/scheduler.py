"""In-app background scheduler (APScheduler).

Replaces the cron job for expiring clients and (optionally) enforcing traffic
quotas. Enabled via SCHEDULER_ENABLED; intervals via EXPIRE_INTERVAL_MINUTES
and TRAFFIC_CHECK_INTERVAL_MINUTES.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from ..config import settings
from ..database import SessionLocal
from .expire import expire_clients
from .sync import refresh_connected
from .traffic import enforce_traffic_quotas

logger = logging.getLogger("wam.scheduler")

_scheduler: BackgroundScheduler | None = None


def _run_expire() -> None:
    db = SessionLocal()
    try:
        res = expire_clients(db)
        if res.get("expired"):
            logger.info("expire job: %s", res)
    except Exception as exc:  # noqa: BLE001
        logger.exception("expire job failed: %s", exc)
    finally:
        db.close()


def _run_traffic() -> None:
    db = SessionLocal()
    try:
        res = enforce_traffic_quotas(db)
        if res.get("disabled"):
            logger.info("traffic job: %s", res)
    except Exception as exc:  # noqa: BLE001
        logger.exception("traffic job failed: %s", exc)
    finally:
        db.close()


def _run_lease_sync() -> None:
    db = SessionLocal()
    try:
        res = refresh_connected(db)
        if res.get("updated"):
            logger.info("lease sync: %s", res)
    except Exception as exc:  # noqa: BLE001
        logger.exception("lease sync job failed: %s", exc)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.SCHEDULER_ENABLED:
        logger.info("Scheduler disabled (SCHEDULER_ENABLED=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(daemon=True)
    sched.add_job(
        _run_expire,
        "interval",
        minutes=max(1, settings.EXPIRE_INTERVAL_MINUTES),
        id="expire_clients",
        replace_existing=True,
    )
    if settings.TRAFFIC_CHECK_ENABLED:
        sched.add_job(
            _run_traffic,
            "interval",
            minutes=max(1, settings.TRAFFIC_CHECK_INTERVAL_MINUTES),
            id="traffic_check",
            replace_existing=True,
        )
    if settings.LEASE_SYNC_ENABLED:
        sched.add_job(
            _run_lease_sync,
            "interval",
            minutes=max(1, settings.LEASE_SYNC_INTERVAL_MINUTES),
            id="lease_sync",
            replace_existing=True,
        )
    sched.start()
    _scheduler = sched
    logger.info(
        "Scheduler started: expire every %s min, traffic check %s",
        settings.EXPIRE_INTERVAL_MINUTES,
        "every %s min" % settings.TRAFFIC_CHECK_INTERVAL_MINUTES
        if settings.TRAFFIC_CHECK_ENABLED else "disabled",
    )
    return sched


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
