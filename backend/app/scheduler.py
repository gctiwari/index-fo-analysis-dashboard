from __future__ import annotations
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import SessionLocal
from app.config import ACTIVE_INDICES
from app.services import tracker
from app.services.market_hours import is_market_open

logger = logging.getLogger("scheduler")

_scheduler: BackgroundScheduler | None = None


def _generate_all():
    db = SessionLocal()
    try:
        for idx in ACTIVE_INDICES:
            try:
                tracker.generate_daily_recommendations(db, idx)
                logger.info("Generated today's recommendation legs for %s", idx)
            except Exception:  # noqa: BLE001
                logger.exception("generate_daily_recommendations failed for %s", idx)
    finally:
        db.close()


def _monitor_all():
    if not is_market_open():
        return
    db = SessionLocal()
    try:
        for idx in ACTIVE_INDICES:
            try:
                tracker.monitor_tick(db, idx)
            except Exception:  # noqa: BLE001
                logger.exception("monitor_tick failed for %s", idx)
    finally:
        db.close()


def _finalize_all():
    db = SessionLocal()
    try:
        for idx in ACTIVE_INDICES:
            try:
                tracker.finalize_day(db, idx)
                logger.info("Finalized day for %s", idx)
            except Exception:  # noqa: BLE001
                logger.exception("finalize_day failed for %s", idx)
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(timezone="Asia/Kolkata")
    # Generate fresh recommendations shortly after the pre-market session settles.
    sched.add_job(_generate_all, CronTrigger(day_of_week="mon-fri", hour=9, minute=16))
    # Poll every 3 minutes through the trading session.
    sched.add_job(_monitor_all, CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/3"))
    # Settle the day shortly after close.
    sched.add_job(_finalize_all, CronTrigger(day_of_week="mon-fri", hour=15, minute=32))
    sched.start()
    _scheduler = sched
    logger.info("Scheduler started (generate 09:16, monitor every 3 min, finalize 15:32 IST, Mon-Fri)")
    return sched
