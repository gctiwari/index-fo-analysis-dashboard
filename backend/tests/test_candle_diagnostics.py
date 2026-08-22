"""
Item 5: monitor_tick_count (how many times we polled) must be distinguishable
from unique_candles_checked (how many distinct real market candles we actually
evaluated) -- repeatedly checking the same completed candle is expected and
fine, but it must not be miscounted as multiple unique candles.
"""
from datetime import datetime, timedelta

import app.services.tracker as tracker
from app.services.market_hours import IST
from tests.conftest import make_recommendation


def test_repeated_checks_of_the_same_candle_increment_tick_count_but_not_unique_count(db_session, mock_completed_candle):
    rec = make_recommendation(db_session, option_type="CALL", entry_trigger_index_level=105.0, stop_index_level=95.0)
    fixed_candle_start = datetime.now(IST) - timedelta(minutes=30)

    # Three ticks all observing the SAME completed candle (same timestamp, same close).
    for _ in range(3):
        mock_completed_candle(close=103.0, is_completed=True, candle_start=fixed_candle_start)
        tracker.monitor_tick(db_session, "NIFTY")
        db_session.refresh(rec)

    assert rec.monitor_tick_count == 3, "should count every poll"
    assert rec.unique_candles_checked == 1, "but only ONE distinct candle was actually observed"


def test_new_candle_timestamp_increments_unique_count(db_session, mock_completed_candle):
    rec = make_recommendation(db_session, option_type="CALL", entry_trigger_index_level=999.0, stop_index_level=1.0)
    candle_1 = datetime.now(IST) - timedelta(minutes=45)
    candle_2 = candle_1 + timedelta(minutes=15)
    candle_3 = candle_2 + timedelta(minutes=15)

    mock_completed_candle(close=103.0, is_completed=True, candle_start=candle_1)
    tracker.monitor_tick(db_session, "NIFTY")
    mock_completed_candle(close=104.0, is_completed=True, candle_start=candle_2)
    tracker.monitor_tick(db_session, "NIFTY")
    mock_completed_candle(close=105.0, is_completed=True, candle_start=candle_3)
    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.monitor_tick_count == 3
    assert rec.unique_candles_checked == 3
    assert rec.last_completed_candle_close == 105.0


def test_last_completed_candle_fields_reflect_the_decisive_candle(db_session, mock_completed_candle):
    rec = make_recommendation(db_session, option_type="CALL", entry_trigger_index_level=105.0, stop_index_level=95.0)
    decisive_candle_start = datetime.now(IST) - timedelta(minutes=15)
    mock_completed_candle(close=106.0, is_completed=True, candle_start=decisive_candle_start)

    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.status == "EXECUTED"
    assert rec.last_completed_candle_close == 106.0
    assert rec.last_completed_candle_timestamp is not None
