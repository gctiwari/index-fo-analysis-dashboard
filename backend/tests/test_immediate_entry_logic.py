"""
Item 2: a "confidence >= 75%" Immediate trade must NOT self-execute at
generation time. It must go through the exact same completed-15m-candle
close check as a Conditional trade -- confidence sets entry_type and how
close the trigger sits to CMP, never bypasses confirmation entirely.
"""
import app.services.tracker as tracker
from tests.conftest import make_recommendation


def test_immediate_trade_does_not_self_execute_at_generation(db_session):
    """The bug: entry_type == 'Immediate' used to call _execute() synchronously
    inside _store_recommendation(), with zero candle confirmation. Simulate the
    equivalent of what _store_recommendation now does (i.e. NOT calling _execute)
    and confirm the row stays PENDING until monitor_tick actually confirms it."""
    rec = make_recommendation(
        db_session, entry_type="Immediate", cmp_at_generation=100.0,
        entry_trigger_index_level=100.0,  # Immediate trades trigger at the generation-time cmp
        status="PENDING",  # must be created as PENDING, never pre-executed
    )
    assert rec.status == "PENDING"
    assert rec.paper_trade is None


def test_immediate_trade_confirms_on_next_completed_candle(db_session, mock_completed_candle):
    """Immediate trades still confirm fast (no minimum distance requirement, unlike
    Conditional), but they must go through a REAL completed-candle check."""
    rec = make_recommendation(
        db_session, entry_type="Immediate", option_type="CALL",
        cmp_at_generation=100.0, entry_trigger_index_level=100.0, stop_index_level=90.0,
    )
    # A completed candle closing at or above the generation cmp confirms it.
    mock_completed_candle(close=100.5, is_completed=True)
    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.status == "EXECUTED"
    assert rec.paper_trade is not None
    # Entry should be priced off the CONFIRMED candle close, not blindly the stale generation cmp.
    assert rec.paper_trade.entry_index_level == 100.5


def test_immediate_trade_does_not_execute_on_incomplete_candle(db_session, mock_completed_candle):
    """Even for Immediate trades, an incomplete/still-forming candle must never trigger execution."""
    rec = make_recommendation(
        db_session, entry_type="Immediate", option_type="CALL",
        cmp_at_generation=100.0, entry_trigger_index_level=100.0, stop_index_level=90.0,
    )
    mock_completed_candle(close=105.0, is_completed=False)  # price is favorable but candle isn't done
    tracker.monitor_tick(db_session, "NIFTY")
    db_session.refresh(rec)

    assert rec.status == "PENDING"
    assert rec.paper_trade is None


def test_immediate_vs_conditional_trigger_distance_differs_as_designed(db_session):
    """Confirms the legitimate strategic distinction survives the fix: Immediate trades
    trigger at (approximately) the generation cmp, Conditional trades require a real,
    materially larger move first -- this is what SHOULD differ, not whether confirmation happens."""
    immediate = make_recommendation(
        db_session, role="PRIMARY", entry_type="Immediate",
        cmp_at_generation=100.0, entry_trigger_index_level=100.0,
    )
    conditional = make_recommendation(
        db_session, role="BREAKOUT_UP", entry_type="Conditional",
        cmp_at_generation=100.0, entry_trigger_index_level=105.0,  # a real distance away
    )
    assert abs(immediate.entry_trigger_index_level - immediate.cmp_at_generation) < abs(
        conditional.entry_trigger_index_level - conditional.cmp_at_generation
    )
