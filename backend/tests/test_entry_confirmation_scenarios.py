"""
The 6 required entry-confirmation scenarios, run against the real
monitor_tick() function with an isolated in-memory DB per test.
"""
import app.services.tracker as tracker
from tests.conftest import make_recommendation


def test_scenario1_trigger_never_reached_becomes_not_executed(db_session, mock_completed_candle):
    rec = make_recommendation(db_session, option_type="CALL", entry_trigger_index_level=105.0, stop_index_level=95.0)
    mock_completed_candle(close=103.0, is_completed=True)  # never reaches 105

    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)
    assert rec.status == "PENDING"  # not yet end of day

    tracker.finalize_day(db_session, "NIFTY")
    db_session.refresh(rec)
    assert rec.status == "NOT_EXECUTED"
    assert "not reached" in rec.not_executed_reason.lower()


def test_scenario2_intrabar_touch_without_15m_close_stays_pending(db_session, mock_completed_candle):
    rec = make_recommendation(db_session, option_type="CALL", entry_trigger_index_level=105.0, stop_index_level=95.0)
    # Completed candle closed at 104 (below trigger) -- even if intrabar price poked above 105,
    # the CLOSE is what matters, and it didn't confirm.
    mock_completed_candle(close=104.0, is_completed=True)

    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.status == "PENDING"
    assert rec.paper_trade is None


def test_scenario3_valid_call_confirmation_executes(db_session, mock_completed_candle):
    rec = make_recommendation(db_session, option_type="CALL", entry_trigger_index_level=105.0, stop_index_level=95.0)
    mock_completed_candle(close=106.0, is_completed=True)

    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.status == "EXECUTED"
    assert rec.paper_trade is not None
    assert rec.paper_trade.status == "OPEN"


def test_scenario4_valid_put_confirmation_executes(db_session, mock_completed_candle):
    rec = make_recommendation(
        db_session, option_type="PUT", direction="Bearish",
        entry_trigger_index_level=95.0, stop_index_level=105.0,
        entry_trigger_desc="Enter on a 15-min close below 95",
    )
    mock_completed_candle(close=94.0, is_completed=True)

    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.status == "EXECUTED"
    assert rec.paper_trade is not None


def test_scenario5_setup_invalidated_before_entry(db_session, mock_completed_candle):
    rec = make_recommendation(db_session, option_type="CALL", entry_trigger_index_level=105.0, stop_index_level=95.0)
    # Price closes at 94 -- THROUGH the stop (95) -- before ever reaching the trigger (105).
    mock_completed_candle(close=94.0, is_completed=True)

    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.status == "INVALIDATED"
    assert rec.invalidated_reason is not None
    assert rec.paper_trade is None


def test_scenario6_invalidated_trade_does_not_later_execute(db_session, mock_completed_candle):
    rec = make_recommendation(db_session, option_type="CALL", entry_trigger_index_level=105.0, stop_index_level=95.0)

    mock_completed_candle(close=94.0, is_completed=True)  # invalidates it
    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)
    assert rec.status == "INVALIDATED"

    # Price now closes above the ORIGINAL trigger -- must NOT flip back to EXECUTED.
    mock_completed_candle(close=110.0, is_completed=True)
    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.status == "INVALIDATED", "an invalidated setup must never later execute"
    assert rec.paper_trade is None
