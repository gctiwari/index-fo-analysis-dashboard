"""
Item 6: explicit tests that the trade lifecycle is a one-way state machine.
Once EXECUTED, INVALIDATED, or NOT_EXECUTED, a recommendation must never
transition again, and a trade must never execute twice.
"""
import app.services.tracker as tracker
from tests.conftest import make_recommendation


def test_already_executed_trade_never_executes_again(db_session, mock_completed_candle):
    rec = make_recommendation(db_session, option_type="CALL", entry_trigger_index_level=105.0, stop_index_level=95.0)
    mock_completed_candle(close=106.0, is_completed=True)

    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)
    assert rec.status == "EXECUTED"
    first_entry_time = rec.paper_trade.entry_time
    first_entry_premium = rec.paper_trade.entry_premium
    paper_trade_id = rec.paper_trade.id

    # Run monitor_tick several more times -- nothing about the EXECUTED recommendation
    # should change, and no second PaperTrade should ever be created for it.
    for _ in range(3):
        mock_completed_candle(close=108.0, is_completed=True)
        tracker.monitor_tick(db_session, "NIFTY")

    db_session.refresh(rec)
    assert rec.status == "EXECUTED"
    assert rec.paper_trade.id == paper_trade_id
    assert rec.paper_trade.entry_time == first_entry_time
    assert rec.paper_trade.entry_premium == first_entry_premium


def test_not_executed_trade_never_executes_later(db_session, mock_completed_candle):
    rec = make_recommendation(db_session, option_type="CALL", entry_trigger_index_level=105.0, stop_index_level=95.0)
    mock_completed_candle(close=103.0, is_completed=True)  # never reaches trigger
    tracker.monitor_tick(db_session, "NIFTY")

    tracker.finalize_day(db_session, "NIFTY")
    db_session.refresh(rec)
    assert rec.status == "NOT_EXECUTED"

    # Even if price now closes well beyond the old trigger, a finalized NOT_EXECUTED
    # recommendation must never execute -- the session is over.
    mock_completed_candle(close=120.0, is_completed=True)
    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.status == "NOT_EXECUTED"
    assert rec.paper_trade is None


def test_closed_paper_trade_is_never_reopened_or_overwritten(db_session, mock_completed_candle):
    rec = make_recommendation(
        db_session, option_type="CALL", entry_trigger_index_level=105.0, stop_index_level=95.0,
        target_index_1=115.0,  # target premium is auto-derived consistently from this by the fixture
    )
    mock_completed_candle(close=106.0, is_completed=True)
    tracker.monitor_tick(db_session, "NIFTY")  # executes

    # Push price up hard enough to hit target 1 and close the position.
    mock_completed_candle(close=140.0, is_completed=True)
    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)
    assert rec.paper_trade.status == "CLOSED"
    first_exit_premium = rec.paper_trade.exit_premium
    first_pnl = rec.paper_trade.pnl_rupees

    # Further ticks must never re-close or overwrite the exit.
    mock_completed_candle(close=200.0, is_completed=True)
    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.paper_trade.status == "CLOSED"
    assert rec.paper_trade.exit_premium == first_exit_premium
    assert rec.paper_trade.pnl_rupees == first_pnl


def test_state_machine_guard_ignores_non_pending_rows_directly(db_session):
    """Defense-in-depth: _execute() itself must refuse to act on a non-PENDING row,
    even if somehow called directly rather than via the normal monitor_tick flow."""
    from datetime import datetime
    rec = make_recommendation(db_session, status="NOT_EXECUTED")
    tracker._execute(db_session, rec, entry_index_level=100.0, entry_premium=50.0, entry_time=datetime.now())
    db_session.refresh(rec)
    assert rec.status == "NOT_EXECUTED"
    assert rec.paper_trade is None
