"""
Daily trade-tracking / paper-trading engine.

Lifecycle per index per trading day, PER ROLE (up to 3 roles can coexist --
see models_db.py's Recommendation docstring for what each role means):
  1. generate_daily_recommendations() -- once per day, idempotent per role.
     Calls the analysis engine once and derives all roles from it. If a role
     has no valid idea (e.g. Primary fails the confluence bar, or a
     breakout level is too close to CMP to be meaningful), that role is
     stored as NO_SIGNAL so history has no silent gaps.
  2. monitor_tick() -- called repeatedly during market hours by the
     scheduler. Triggers PENDING -> EXECUTED (creates a PaperTrade) when the
     entry condition is met, and manages OPEN paper trades against
     target/stop. Operates across ALL roles for the index automatically
     (it just queries every PENDING/OPEN row for today, regardless of role).
  3. finalize_day() -- called once after market close. Any PENDING
     recommendation left untriggered becomes NOT_EXECUTED. Any OPEN paper
     trade is closed at the last traded price (EOD_EXIT). Also role-agnostic.
"""
from __future__ import annotations
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models_db import Recommendation, PaperTrade
from app.data.fetcher import get_ohlcv, get_last_price, get_last_completed_candle, DataUnavailableError
from app.analysis.indicators import build_indicator_snapshot
from app.analysis.patterns import detect_candlesticks, detect_chart_patterns
from app.analysis.levels import trend_structure, support_resistance
from app.analysis.confluence import build_confluence
from app.analysis.trades import generate_trade_idea, generate_breakout_bracket, estimate_premium
from app.services.market_hours import today_ist, now_ist
from app.config import INDEX_REGISTRY

logger = logging.getLogger("services.tracker")

MTF_TIMEFRAMES = ["1wk", "1d", "4h", "1h", "15m"]
ROLES = ["PRIMARY", "BREAKOUT_UP", "BREAKOUT_DOWN"]


def _run_analysis(index_key: str):
    """
    Re-runs the same pipeline as the /outlook endpoint. Indicators, patterns,
    trend structure and S/R all legitimately need the daily OHLCV bar (that's
    what they're computed from) -- but the reference "cmp" used for
    entry-trigger math and stored as cmp_at_generation now comes from
    get_last_price() (the SAME live-tick source monitor_tick uses), not the
    daily bar's close. Previously these were two different data paths that
    could disagree by a small, inconsistent margin (RCA finding: CMP source
    mismatch). Falls back to the daily bar's close only if a live price
    genuinely can't be fetched, so generation never hard-fails over this.
    """
    daily_df = get_ohlcv(index_key, "1d")
    try:
        cmp = get_last_price(index_key)
    except DataUnavailableError:
        cmp = float(daily_df["close"].iloc[-1])
    ind = build_indicator_snapshot(daily_df)
    candle_patterns = detect_candlesticks(daily_df, "1d")
    chart_patterns = detect_chart_patterns(daily_df, "1d")
    all_patterns = candle_patterns + chart_patterns
    levels = support_resistance(daily_df)
    trends = []
    for tf in MTF_TIMEFRAMES:
        try:
            tf_df = daily_df if tf == "1d" else get_ohlcv(index_key, tf)
            trends.append(trend_structure(tf_df, tf))
        except DataUnavailableError:
            continue
    confluence = build_confluence(ind, trends, all_patterns, levels, cmp)
    return cmp, ind, all_patterns, levels, confluence


def _store_recommendation(db: Session, index_key: str, trade_date, role: str, cmp: float, confluence: dict, idea: dict | None, no_signal_reason: str | None) -> Recommendation:
    if idea is None:
        rec = Recommendation(
            index_key=index_key, trade_date=trade_date, role=role,
            status="NO_SIGNAL", cmp_at_generation=cmp, confidence_score=confluence["confidence"],
            no_signal_reason=no_signal_reason,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return rec

    rec = Recommendation(
        index_key=index_key, trade_date=trade_date, role=role,
        status="PENDING",
        direction=idea["direction"],
        option_type=idea["option_type"],
        strike=idea["strike"],
        expiry=idea["expiry"],
        lot_size=idea["lot_size"],
        cmp_at_generation=cmp,
        premium_at_generation=idea["estimated_premium"],
        entry_type=idea["entry_type"],
        entry_trigger_desc=idea["entry_trigger"],
        entry_trigger_index_level=idea["_entry_trigger_index_level"],
        target_index_1=idea["_target_index_1"],
        target_index_2=idea["_target_index_2"],
        target_index_3=idea["_target_index_3"],
        stop_index_level=idea["_stop_index_level"],
        target_premium_1=idea["target_1"],
        target_premium_2=idea["target_2"],
        target_premium_3=idea["target_3"],
        stop_premium=idea["hard_stop_loss"],
        atr_pct_at_generation=idea["_atr_pct"],
        confidence_score=confluence["confidence"],
        reasoning=idea["reasoning"],
        raw_json=idea,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    # Immediate-entry ideas (Primary only, when confidence is high) are considered confirmed at generation time.
    if rec.entry_type == "Immediate":
        _execute(db, rec, entry_index_level=cmp, entry_premium=rec.premium_at_generation, entry_time=now_ist().replace(tzinfo=None))

    return rec


def generate_daily_recommendations(db: Session, index_key: str, force: bool = False) -> list[Recommendation]:
    """Idempotent per role: returns today's existing rows if present, generates any missing ones."""
    trade_date = today_ist()
    existing = {
        r.role: r for r in db.query(Recommendation)
        .filter(Recommendation.index_key == index_key, Recommendation.trade_date == trade_date)
        .all()
    }

    if force:
        for r in existing.values():
            if r.paper_trade:
                db.delete(r.paper_trade)
            db.delete(r)
        db.flush()
        existing = {}

    missing_roles = [r for r in ROLES if r not in existing]
    if not missing_roles:
        return [existing[r] for r in ROLES]

    cmp, ind, patterns, levels, confluence = _run_analysis(index_key)
    breakout_ideas = {i["direction"].startswith("Bullish") and "BREAKOUT_UP" or "BREAKOUT_DOWN": i
                       for i in generate_breakout_bracket(index_key, cmp, ind, levels, confluence)}

    results: dict[str, Recommendation] = dict(existing)

    if "PRIMARY" in missing_roles:
        idea = generate_trade_idea(index_key, cmp, confluence, ind, patterns, levels)
        reason = (
            f"Confluence did not clear the high-conviction bar (bias: {confluence['bias']}, "
            f"confidence: {confluence['confidence']:.0f}%)."
        ) if idea is None else None
        results["PRIMARY"] = _store_recommendation(db, index_key, trade_date, "PRIMARY", cmp, confluence, idea, reason)

    if "BREAKOUT_UP" in missing_roles:
        idea = breakout_ideas.get("BREAKOUT_UP")
        reason = None if idea else (
            "No resistance level within a realistic breakout distance was found (either too close to the "
            "current price to be meaningful, or the nearest structural resistance is further away than this "
            "app's own target ladder would realistically reach). WAIT rather than forcing a distant trigger."
        )
        results["BREAKOUT_UP"] = _store_recommendation(db, index_key, trade_date, "BREAKOUT_UP", cmp, confluence, idea, reason)

    if "BREAKOUT_DOWN" in missing_roles:
        idea = breakout_ideas.get("BREAKOUT_DOWN")
        reason = None if idea else (
            "No support level within a realistic breakdown distance was found (either too close to the "
            "current price to be meaningful, or the nearest structural support is further away than this "
            "app's own target ladder would realistically reach). WAIT rather than forcing a distant trigger."
        )
        results["BREAKOUT_DOWN"] = _store_recommendation(db, index_key, trade_date, "BREAKOUT_DOWN", cmp, confluence, idea, reason)

    return [results[r] for r in ROLES]


def _dte_remaining(expiry_str: str) -> int:
    from datetime import date as _date
    try:
        exp = _date.fromisoformat(expiry_str)
        return max((exp - today_ist()).days, 0)
    except Exception:  # noqa: BLE001
        return 1


def _execute(db: Session, rec: Recommendation, entry_index_level: float, entry_premium: float, entry_time: datetime):
    trade = PaperTrade(
        recommendation_id=rec.id,
        index_key=rec.index_key,
        trade_date=rec.trade_date,
        entry_index_level=entry_index_level,
        entry_premium=entry_premium,
        entry_time=entry_time,
        mfe_premium=entry_premium,
        targets_hit=[],
        status="OPEN",
        outcome="OPEN",
    )
    rec.status = "EXECUTED"
    db.add(trade)
    db.add(rec)
    db.commit()


def _close(db: Session, trade: PaperTrade, exit_index_level: float, exit_premium: float, exit_time: datetime, outcome: str):
    trade.exit_index_level = exit_index_level
    trade.exit_premium = exit_premium
    trade.exit_time = exit_time
    trade.status = "CLOSED"
    trade.outcome = outcome
    trade.stop_hit = outcome == "STOP_LOSS"
    lot_size = trade.recommendation.lot_size or 1
    trade.pnl_rupees = round((exit_premium - trade.entry_premium) * lot_size, 1)
    trade.pnl_pct = round((exit_premium - trade.entry_premium) / trade.entry_premium * 100, 2) if trade.entry_premium else 0.0
    db.add(trade)
    db.commit()


def monitor_tick(db: Session, index_key: str):
    """
    One monitoring pass: trigger pending entries, manage open paper trades,
    detect invalidation.

    RCA FIX: previously this compared a single live tick against the
    trigger (`cmp >= trigger`), while every generated trade's own
    entry_trigger text says "enter on a 15-min close beyond X". That was a
    real mismatch between the stated condition and the executed one (Step F
    of the RCA). This now fetches the most recently COMPLETED 15-minute
    candle and checks ITS close -- matching the trade's own stated rule
    exactly. A live tick is still recorded as a diagnostic (last_price_checked)
    on every call so "how close are we" can be shown even between candle
    closes, but it is no longer what decides EXECUTED.
    """
    trade_date = today_ist()
    try:
        candle = get_last_completed_candle(index_key, "15m")
    except DataUnavailableError as exc:
        logger.warning("monitor_tick: price unavailable for %s: %s", index_key, exc)
        return
    confirmed_price = candle["close"]

    # Live tick, best-effort, for diagnostics/live-status display only -- not used for trigger decisions.
    try:
        live_tick = get_last_price(index_key)
    except DataUnavailableError:
        live_tick = confirmed_price

    now = now_ist().replace(tzinfo=None)

    # 1. Trigger pending entries (and detect invalidation) using the CONFIRMED candle close.
    pending = (
        db.query(Recommendation)
        .filter(Recommendation.index_key == index_key, Recommendation.trade_date == trade_date, Recommendation.status == "PENDING")
        .all()
    )
    for rec in pending:
        rec.monitor_tick_count = (rec.monitor_tick_count or 0) + 1
        rec.last_price_checked = live_tick
        rec.last_price_checked_at = now
        rec.last_check_source = candle["source"]

        # Track max favorable excursion toward the trigger, for diagnostics even when it never fires.
        if rec.option_type == "CALL":
            rec.mfe_index_level = max(rec.mfe_index_level or live_tick, live_tick)
        else:
            rec.mfe_index_level = min(rec.mfe_index_level or live_tick, live_tick)

        triggered = False
        if candle["is_completed"] and rec.entry_trigger_index_level is not None:
            if rec.option_type == "CALL":
                triggered = confirmed_price >= rec.entry_trigger_index_level
            elif rec.option_type == "PUT":
                triggered = confirmed_price <= rec.entry_trigger_index_level

        if triggered:
            rec.trigger_reached_at = now
            dte = _dte_remaining(rec.expiry)
            premium = estimate_premium(confirmed_price, rec.strike, dte, rec.atr_pct_at_generation, rec.option_type)
            _execute(db, rec, entry_index_level=confirmed_price, entry_premium=premium, entry_time=now)
            continue

        # Invalidation check: if price has already closed through this trade's OWN stop level
        # in the adverse direction WITHOUT ever triggering, the setup's premise is broken --
        # this is a materially different outcome than "just never got there," so it shouldn't
        # be silently reported as plain NOT_EXECUTED at end of day (RCA Step 6).
        if candle["is_completed"] and rec.stop_index_level is not None:
            adverse = (
                confirmed_price <= rec.stop_index_level if rec.option_type == "CALL"
                else confirmed_price >= rec.stop_index_level
            )
            if adverse:
                rec.status = "INVALIDATED"
                rec.invalidated_reason = (
                    f"Price closed at {confirmed_price:.0f} on a completed 15-min candle, through this trade's "
                    f"own stop level ({rec.stop_index_level:.0f}), before the entry trigger "
                    f"({rec.entry_trigger_index_level:.0f}) was ever reached. The setup's premise no longer holds."
                )
                rec.invalidated_at = now

        db.add(rec)
    db.commit()

    # 2. Manage open paper trades. Deliberately uses the live tick, not the completed-candle
    # close used for entries above: once in a position, a stop-loss should react to the current
    # price immediately rather than waiting up to 15 minutes to confirm a close -- waiting would
    # add avoidable slippage risk to exits, which is the opposite of what a stop is for. Entries
    # and exits having different confirmation strictness is intentional, not an inconsistency.
    open_trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.index_key == index_key, PaperTrade.trade_date == trade_date, PaperTrade.status == "OPEN")
        .all()
    )
    for trade in open_trades:
        rec = trade.recommendation
        dte = _dte_remaining(rec.expiry)
        premium = estimate_premium(live_tick, rec.strike, dte, rec.atr_pct_at_generation, rec.option_type)

        trade.mfe_premium = max(trade.mfe_premium or premium, premium)
        hit = list(trade.targets_hit or [])
        if trade.mfe_premium >= rec.target_premium_3 and "target_3" not in hit:
            hit.append("target_3")
        elif trade.mfe_premium >= rec.target_premium_2 and "target_2" not in hit:
            hit.append("target_2")
        elif trade.mfe_premium >= rec.target_premium_1 and "target_1" not in hit:
            hit.append("target_1")
        trade.targets_hit = hit
        db.add(trade)

        if premium <= rec.stop_premium:
            _close(db, trade, exit_index_level=live_tick, exit_premium=premium, exit_time=now, outcome="STOP_LOSS")
        elif premium >= rec.target_premium_1:
            # Conservative single-target exit discipline (matches the "hard stop" style risk
            # management already used elsewhere) -- exits in full at Target 1.
            _close(db, trade, exit_index_level=live_tick, exit_premium=premium, exit_time=now, outcome="TARGET_1")
        else:
            db.commit()


def finalize_day(db: Session, index_key: str, trade_date=None):
    """Settle anything still open/pending for the given trade_date (defaults to today).
    Passing a past date lets a stale PENDING row from a day the server wasn't running
    late enough to auto-finalize get lazily settled the next time it's actually looked at
    (e.g. via the /yesterday endpoint), instead of showing a permanently-stuck PENDING
    for a session that's obviously long over."""
    trade_date = trade_date or today_ist()
    is_today = trade_date == today_ist()
    now = now_ist().replace(tzinfo=None)

    if is_today:
        # Settling the current session -- use the live price, as before.
        try:
            cmp = get_last_price(index_key)
        except DataUnavailableError:
            cmp = None
    else:
        # Settling a PAST session that was never properly closed out (server wasn't
        # running at 15:32 IST that day) -- use THAT day's actual close, never today's
        # live price, or the exit would be priced on the wrong day entirely.
        try:
            daily_df = get_ohlcv(index_key, "1d")
            day_rows = daily_df[daily_df.index.date == trade_date]
            cmp = float(day_rows["close"].iloc[-1]) if len(day_rows) else None
        except DataUnavailableError:
            cmp = None

    pending = (
        db.query(Recommendation)
        .filter(Recommendation.index_key == index_key, Recommendation.trade_date == trade_date, Recommendation.status == "PENDING")
        .all()
    )
    for rec in pending:
        rec.status = "NOT_EXECUTED"
        if rec.mfe_index_level is not None and rec.entry_trigger_index_level is not None:
            gap = abs(rec.entry_trigger_index_level - rec.mfe_index_level)
            rec.not_executed_reason = (
                f"Entry trigger ({rec.entry_trigger_index_level:.0f}) was not reached before market close. "
                f"Best price seen toward it was {rec.mfe_index_level:.0f} ({gap:.0f} points short). "
                f"Checked {rec.monitor_tick_count or 0} time(s) during the session."
            )
        else:
            rec.not_executed_reason = (
                f"Entry trigger was not reached before market close. Checked {rec.monitor_tick_count or 0} "
                f"time(s) during the session -- a low count here usually means the monitoring process wasn't "
                f"running continuously, not that price genuinely stayed away from the trigger."
            )
        db.add(rec)

    open_trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.index_key == index_key, PaperTrade.trade_date == trade_date, PaperTrade.status == "OPEN")
        .all()
    )
    for trade in open_trades:
        rec = trade.recommendation
        if cmp is not None:
            dte = _dte_remaining(rec.expiry)
            premium = estimate_premium(cmp, rec.strike, dte, rec.atr_pct_at_generation, rec.option_type)
        else:
            premium = trade.entry_premium
        _close(db, trade, exit_index_level=cmp or trade.entry_index_level, exit_premium=premium, exit_time=now, outcome="EOD_EXIT")

    db.commit()


def most_recent_prior_session_date(db: Session, index_key: str):
    """
    The most recent trade_date strictly before today that actually has
    recommendation rows for this index -- robust to weekends/holidays
    without needing a holiday calendar (if today is Monday, this correctly
    finds Friday rather than blindly subtracting one calendar day, which
    would land on Sunday and find nothing).
    """
    row = (
        db.query(Recommendation.trade_date)
        .filter(Recommendation.index_key == index_key, Recommendation.trade_date < today_ist())
        .order_by(Recommendation.trade_date.desc())
        .first()
    )
    return row[0] if row else None


def get_session(db: Session, index_key: str, trade_date) -> list[Recommendation]:
    """
    Read the (already-generated) recommendations for a specific past date.
    Lazily finalizes anything still PENDING for that date first -- a day
    that's already over should never show a permanently-stuck PENDING just
    because the server wasn't running at 15:32 IST that particular day.
    """
    still_pending = (
        db.query(Recommendation)
        .filter(Recommendation.index_key == index_key, Recommendation.trade_date == trade_date, Recommendation.status == "PENDING")
        .count()
    )
    if still_pending:
        finalize_day(db, index_key, trade_date=trade_date)

    recs = (
        db.query(Recommendation)
        .filter(Recommendation.index_key == index_key, Recommendation.trade_date == trade_date)
        .all()
    )
    order = {"PRIMARY": 0, "BREAKOUT_UP": 1, "BREAKOUT_DOWN": 2}
    recs.sort(key=lambda r: order.get(r.role, 99))
    return recs


def get_live_status(index_key: str, rec: Recommendation) -> dict:
    """
    Read-only snapshot of where the live market sits relative to today's
    LOCKED recommendation. This never changes the recommendation itself --
    it only reports distance-to-trigger / distance-to-target so the UI can
    show "here's the plan, here's how close we are" instead of a shifting
    trade idea.
    """
    try:
        cmp = get_last_price(index_key)
    except DataUnavailableError:
        return {"available": False, "current_price": None}

    out = {"available": True, "current_price": round(cmp, 1)}
    # Diagnostics available regardless of status -- directly answers "was this actually being watched".
    out["monitor_tick_count"] = rec.monitor_tick_count or 0
    out["last_price_checked_at"] = rec.last_price_checked_at.isoformat() if rec.last_price_checked_at else None
    out["mfe_index_level"] = rec.mfe_index_level

    if rec.status == "PENDING" and rec.entry_trigger_index_level:
        distance = cmp - rec.entry_trigger_index_level
        if rec.option_type == "PUT":
            distance = -distance
        out["distance_to_trigger"] = round(distance, 1)
        out["trigger_reached"] = distance >= 0

    if rec.status == "EXECUTED" and rec.paper_trade and rec.paper_trade.status == "OPEN":
        trade = rec.paper_trade
        dte = _dte_remaining(rec.expiry)
        current_premium = estimate_premium(cmp, rec.strike, dte, rec.atr_pct_at_generation, rec.option_type)
        out["current_premium"] = current_premium
        out["unrealized_pnl_pct"] = round((current_premium - trade.entry_premium) / trade.entry_premium * 100, 2) if trade.entry_premium else 0.0
        out["progress_to_target_1_pct"] = round(
            max(0.0, min(1.0, (current_premium - trade.entry_premium) / (rec.target_premium_1 - trade.entry_premium))) * 100, 1
        ) if rec.target_premium_1 and rec.target_premium_1 != trade.entry_premium else 0.0

    return out


def compute_performance(db: Session, index_key: str | None = None) -> dict:
    q = db.query(Recommendation)
    if index_key:
        q = q.filter(Recommendation.index_key == index_key)
    recs = q.all()

    total_days = len(recs)
    signal_days = [r for r in recs if r.status != "NO_SIGNAL"]
    executed = [r for r in recs if r.status == "EXECUTED"]
    not_executed = [r for r in recs if r.status == "NOT_EXECUTED"]
    no_signal = [r for r in recs if r.status == "NO_SIGNAL"]

    closed_trades = [r.paper_trade for r in executed if r.paper_trade and r.paper_trade.status == "CLOSED"]
    open_trades = [r.paper_trade for r in executed if r.paper_trade and r.paper_trade.status == "OPEN"]

    wins = [t for t in closed_trades if (t.pnl_pct or 0) > 0]
    losses = [t for t in closed_trades if (t.pnl_pct or 0) <= 0]

    pct_executed = round(len(executed) / len(signal_days) * 100, 1) if signal_days else 0.0
    win_rate = round(len(wins) / len(closed_trades) * 100, 1) if closed_trades else 0.0
    avg_return_pct = round(sum(t.pnl_pct or 0 for t in closed_trades) / len(closed_trades), 2) if closed_trades else 0.0
    total_pnl_rupees = round(sum(t.pnl_rupees or 0 for t in closed_trades), 1)
    avg_win_pct = round(sum(t.pnl_pct for t in wins) / len(wins), 2) if wins else 0.0
    avg_loss_pct = round(sum(t.pnl_pct for t in losses) / len(losses), 2) if losses else 0.0
    best_trade_pct = round(max((t.pnl_pct or 0 for t in closed_trades), default=0.0), 2)
    worst_trade_pct = round(min((t.pnl_pct or 0 for t in closed_trades), default=0.0), 2)

    return {
        "index": index_key or "ALL",
        "total_trading_days_tracked": total_days,
        "signal_days": len(signal_days),
        "no_signal_days": len(no_signal),
        "executed_count": len(executed),
        "not_executed_count": len(not_executed),
        "pct_executed": pct_executed,
        "open_trades_count": len(open_trades),
        "closed_trades_count": len(closed_trades),
        "win_rate_pct": win_rate,
        "avg_return_pct_per_trade": avg_return_pct,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "best_trade_pct": best_trade_pct,
        "worst_trade_pct": worst_trade_pct,
        "total_pnl_rupees_per_lot": total_pnl_rupees,
    }


def compute_equity_curve(db: Session, index_key: str | None = None) -> list[dict]:
    """Chronological, cumulative P&L across every CLOSED paper trade -- the running equity curve."""
    q = db.query(PaperTrade).filter(PaperTrade.status == "CLOSED")
    if index_key:
        q = q.filter(PaperTrade.index_key == index_key)
    trades = q.order_by(PaperTrade.exit_time.asc()).all()

    cum_rupees = 0.0
    cum_pct = 0.0  # simple additive sum of per-trade % returns -- readable curve, not compounded
    curve: list[dict] = [{
        "seq": 0, "trade_date": None, "exit_time": None, "index": None,
        "trade_pnl_rupees": 0.0, "trade_pnl_pct": 0.0,
        "cumulative_pnl_rupees": 0.0, "cumulative_pnl_pct": 0.0, "outcome": "START",
    }]
    for i, t in enumerate(trades, start=1):
        cum_rupees += (t.pnl_rupees or 0.0)
        cum_pct += (t.pnl_pct or 0.0)
        curve.append({
            "seq": i,
            "trade_date": t.trade_date.isoformat(),
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "index": t.index_key,
            "trade_pnl_rupees": t.pnl_rupees,
            "trade_pnl_pct": t.pnl_pct,
            "cumulative_pnl_rupees": round(cum_rupees, 1),
            "cumulative_pnl_pct": round(cum_pct, 2),
            "outcome": t.outcome,
        })
    return curve
