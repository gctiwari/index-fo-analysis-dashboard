from __future__ import annotations
import io
from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.config import INDEX_REGISTRY, ACTIVE_INDICES
from app.models_db import Recommendation, PaperTrade
from app.services import tracker
from app.services.market_hours import today_ist, is_market_open, now_ist
from app.services.export import build_trade_log_dataframe, to_csv_bytes, to_xlsx_bytes

router = APIRouter()

# RCA FIX (see backend/README.md "Audit: why trades weren't executing"): monitoring
# previously only ran on the APScheduler's fixed 3-minute cron, which requires the
# backend process to stay alive continuously and unattended. Opening/refreshing the
# app did nothing to check triggers. This throttle lets /today ALSO run a monitoring
# pass as a side effect during market hours -- so any real interaction with the app
# checks live triggers, closing the coverage gap regardless of whether the dedicated
# background scheduler process happened to be alive at that exact moment. Throttled
# per-index to a floor of ~20s between opportunistic ticks so several browser tabs or
# rapid refreshes don't hammer the upstream data source beyond what's useful.
_last_opportunistic_tick: dict[str, float] = {}
_OPPORTUNISTIC_COOLDOWN_SECONDS = 20


def _maybe_opportunistic_monitor(db: Session, index_key: str):
    if not is_market_open():
        return
    import time as _time
    last = _last_opportunistic_tick.get(index_key, 0.0)
    now = _time.monotonic()
    if now - last < _OPPORTUNISTIC_COOLDOWN_SECONDS:
        return
    _last_opportunistic_tick[index_key] = now
    try:
        tracker.monitor_tick(db, index_key)
    except Exception:  # noqa: BLE001 -- never let an opportunistic check break the read endpoint
        pass


def _require_active(index_key: str):
    index_key = index_key.upper()
    if index_key not in INDEX_REGISTRY:
        raise HTTPException(404, f"Unknown index '{index_key}'")
    if index_key not in ACTIVE_INDICES:
        raise HTTPException(409, f"No live data source configured for '{index_key}' yet.")
    return index_key


def _rec_to_dict(rec: Recommendation) -> dict:
    return {
        "id": rec.id,
        "index": rec.index_key,
        "role": rec.role,
        "trade_date": rec.trade_date.isoformat(),
        "generated_at": rec.generated_at.isoformat() if rec.generated_at else None,
        "status": rec.status,
        "not_executed_reason": rec.not_executed_reason,
        "no_signal_reason": rec.no_signal_reason,
        "invalidated_reason": rec.invalidated_reason,
        "invalidated_at": rec.invalidated_at.isoformat() if rec.invalidated_at else None,
        "direction": rec.direction,
        "option_type": rec.option_type,
        "strike": rec.strike,
        "expiry": rec.expiry,
        "lot_size": rec.lot_size,
        "cmp_at_generation": rec.cmp_at_generation,
        "premium_at_generation": rec.premium_at_generation,
        "entry_type": rec.entry_type,
        "entry_trigger_desc": rec.entry_trigger_desc,
        "entry_trigger_index_level": rec.entry_trigger_index_level,
        "stop_index_level": rec.stop_index_level,
        "target_premium_1": rec.target_premium_1,
        "target_premium_2": rec.target_premium_2,
        "target_premium_3": rec.target_premium_3,
        "stop_premium": rec.stop_premium,
        "confidence_score": rec.confidence_score,
        "reasoning": rec.reasoning,
        "raw": rec.raw_json,
        "paper_trade": _trade_to_dict(rec.paper_trade) if rec.paper_trade else None,
        # Monitoring diagnostics -- directly answers "was this actually being watched, and how closely"
        "diagnostics": {
            "monitor_tick_count": rec.monitor_tick_count or 0,
            "last_price_checked": rec.last_price_checked,
            "last_price_checked_at": rec.last_price_checked_at.isoformat() if rec.last_price_checked_at else None,
            "last_check_source": rec.last_check_source,
            "mfe_index_level": rec.mfe_index_level,
            "trigger_reached_at": rec.trigger_reached_at.isoformat() if rec.trigger_reached_at else None,
        },
    }


def _trade_to_dict(trade: PaperTrade) -> dict:
    return {
        "id": trade.id,
        "index": trade.index_key,
        "role": trade.recommendation.role if trade.recommendation else None,
        "trade_date": trade.trade_date.isoformat(),
        "entry_index_level": trade.entry_index_level,
        "entry_premium": trade.entry_premium,
        "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
        "exit_index_level": trade.exit_index_level,
        "exit_premium": trade.exit_premium,
        "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
        "targets_hit": trade.targets_hit or [],
        "stop_hit": trade.stop_hit,
        "status": trade.status,
        "outcome": trade.outcome,
        "pnl_rupees": trade.pnl_rupees,
        "pnl_pct": trade.pnl_pct,
    }


@router.get("/tracking/{index_key}/today")
def get_today(index_key: str, db: Session = Depends(get_db)):
    """
    Returns all of today's LOCKED recommendation legs for this index (up to
    3: PRIMARY, BREAKOUT_UP, BREAKOUT_DOWN). Each is generated once and then
    fixed for the rest of the day -- only each leg's "live" block (current
    price, distance to trigger, unrealized P&L) updates on repeated calls.

    Also opportunistically runs a monitoring pass (throttled, market-hours
    only) -- see the RCA fix note above _maybe_opportunistic_monitor. This
    means checking this endpoint is itself part of how triggers get detected
    now, not just the background scheduler.
    """
    index_key = _require_active(index_key)
    recs = tracker.generate_daily_recommendations(db, index_key)  # idempotent per role -- generates if missing, then LOCKED
    _maybe_opportunistic_monitor(db, index_key)
    db.expire_all()  # pick up any changes monitor_tick just made to the same objects
    recs = (
        db.query(Recommendation)
        .filter(Recommendation.index_key == index_key, Recommendation.trade_date == today_ist())
        .all()
    )
    recs_by_role = {r.role: r for r in recs}
    ordered = [recs_by_role[r] for r in ["PRIMARY", "BREAKOUT_UP", "BREAKOUT_DOWN"] if r in recs_by_role]
    out = []
    for rec in ordered:
        payload = _rec_to_dict(rec)
        payload["live"] = tracker.get_live_status(index_key, rec)
        out.append(payload)
    return out


@router.post("/tracking/{index_key}/generate-now")
def generate_now(index_key: str, db: Session = Depends(get_db)):
    """Testing-only override: wipes and regenerates ALL of today's legs (Primary + both
    breakout watches) at the current price. Normal use shouldn't need this."""
    index_key = _require_active(index_key)
    recs = tracker.generate_daily_recommendations(db, index_key, force=True)
    return [_rec_to_dict(r) for r in recs]


@router.post("/tracking/{index_key}/check-now")
def check_now(index_key: str, db: Session = Depends(get_db)):
    """Manual trigger for one monitoring pass -- useful outside the 3-min scheduler cadence.
    Checks all of today's legs (Primary + both breakout watches)."""
    index_key = _require_active(index_key)
    tracker.monitor_tick(db, index_key)
    recs = (
        db.query(Recommendation)
        .filter(Recommendation.index_key == index_key, Recommendation.trade_date == today_ist())
        .all()
    )
    return [_rec_to_dict(r) for r in recs] if recs else {"status": "no_recommendation_today"}


@router.post("/tracking/{index_key}/finalize-now")
def finalize_now(index_key: str, db: Session = Depends(get_db)):
    """Manual EOD settlement -- useful for demos without waiting for market close."""
    index_key = _require_active(index_key)
    tracker.finalize_day(db, index_key)
    return {"status": "finalized", "index": index_key}


@router.get("/tracking/{index_key}/paper-trades")
def list_paper_trades(index_key: str, db: Session = Depends(get_db), status: str | None = Query(None, description="OPEN or CLOSED")):
    index_key = _require_active(index_key)
    q = db.query(PaperTrade).filter(PaperTrade.index_key == index_key)
    if status:
        q = q.filter(PaperTrade.status == status.upper())
    trades = q.order_by(PaperTrade.trade_date.desc()).all()
    return [_trade_to_dict(t) for t in trades]


@router.get("/tracking/{index_key}/not-executed")
def list_not_executed(index_key: str, db: Session = Depends(get_db)):
    index_key = _require_active(index_key)
    recs = (
        db.query(Recommendation)
        .filter(Recommendation.index_key == index_key, Recommendation.status == "NOT_EXECUTED")
        .order_by(Recommendation.trade_date.desc())
        .all()
    )
    return [_rec_to_dict(r) for r in recs]


@router.get("/tracking/{index_key}/invalidated")
def list_invalidated(index_key: str, db: Session = Depends(get_db)):
    """
    Kept as a genuinely distinct list from /not-executed (RCA Step 6): a
    trade that broke through its own stop level before ever triggering had
    its setup invalidated -- a materially different outcome from one that
    simply never got close to the entry trigger.
    """
    index_key = _require_active(index_key)
    recs = (
        db.query(Recommendation)
        .filter(Recommendation.index_key == index_key, Recommendation.status == "INVALIDATED")
        .order_by(Recommendation.trade_date.desc())
        .all()
    )
    return [_rec_to_dict(r) for r in recs]


@router.get("/tracking/{index_key}/history")
def get_history(index_key: str, db: Session = Depends(get_db), limit: int = 60):
    index_key = _require_active(index_key)
    recs = (
        db.query(Recommendation)
        .filter(Recommendation.index_key == index_key)
        .order_by(Recommendation.trade_date.desc())
        .limit(limit)
        .all()
    )
    return [_rec_to_dict(r) for r in recs]


@router.get("/performance")
def performance_all(db: Session = Depends(get_db)):
    overall = tracker.compute_performance(db, None)
    per_index = [tracker.compute_performance(db, idx) for idx in ACTIVE_INDICES]
    return {"overall": overall, "per_index": per_index}


@router.get("/performance/{index_key}")
def performance_one(index_key: str, db: Session = Depends(get_db)):
    index_key = _require_active(index_key)
    return tracker.compute_performance(db, index_key)


@router.get("/performance/{index_key}/equity-curve")
def equity_curve_one(index_key: str, db: Session = Depends(get_db)):
    index_key = _require_active(index_key)
    return tracker.compute_equity_curve(db, index_key)


@router.get("/performance-equity-curve")
def equity_curve_all(db: Session = Depends(get_db)):
    return tracker.compute_equity_curve(db, None)


def _csv_response(df, filename: str) -> StreamingResponse:
    data = to_csv_bytes(df)
    return StreamingResponse(
        io.BytesIO(data), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _xlsx_response(df, filename: str) -> StreamingResponse:
    data = to_xlsx_bytes(df)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/{index_key}/csv")
def export_csv(index_key: str, db: Session = Depends(get_db)):
    index_key = _require_active(index_key)
    df = build_trade_log_dataframe(db, index_key)
    return _csv_response(df, f"{index_key}_trade_log_{today_ist().isoformat()}.csv")


@router.get("/export/{index_key}/xlsx")
def export_xlsx(index_key: str, db: Session = Depends(get_db)):
    index_key = _require_active(index_key)
    df = build_trade_log_dataframe(db, index_key)
    return _xlsx_response(df, f"{index_key}_trade_log_{today_ist().isoformat()}.xlsx")


@router.get("/export-all/csv")
def export_all_csv(db: Session = Depends(get_db)):
    df = build_trade_log_dataframe(db, None)
    return _csv_response(df, f"all_indices_trade_log_{today_ist().isoformat()}.csv")


@router.get("/export-all/xlsx")
def export_all_xlsx(db: Session = Depends(get_db)):
    df = build_trade_log_dataframe(db, None)
    return _xlsx_response(df, f"all_indices_trade_log_{today_ist().isoformat()}.xlsx")
