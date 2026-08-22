"""
Confirms get_last_completed_candle() correctly distinguishes a genuinely
completed candle from one still forming -- the core of the entry-
confirmation fix (never execute on an incomplete candle).
"""
from datetime import datetime, timedelta

from app.services.market_hours import IST
import app.data.fetcher as fetcher


def _make_15m_df(last_candle_start_ist: datetime, closes: list[float]):
    import pandas as pd
    n = len(closes)
    starts = [last_candle_start_ist - timedelta(minutes=15 * (n - 1 - i)) for i in range(n)]
    idx = pd.DatetimeIndex(starts)
    return pd.DataFrame({
        "open": closes, "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
        "close": closes, "volume": [0] * n,
    }, index=idx)


def test_fully_elapsed_candle_is_used_as_is(monkeypatch):
    now = datetime.now(IST)
    last_candle_start = now - timedelta(minutes=20)  # started 20 min ago, 15m period ended 5 min ago
    df = _make_15m_df(last_candle_start, [100, 101, 102])
    monkeypatch.setattr(fetcher, "_download", lambda ticker, period, interval, retries=2: df)

    result = fetcher.get_last_completed_candle("NIFTY", "15m")

    assert result["is_completed"] is True
    assert result["close"] == 102.0
    assert result["source"] == "completed_15m_close"


def test_incomplete_candle_falls_back_to_previous_completed_one(monkeypatch):
    now = datetime.now(IST)
    last_candle_start = now - timedelta(minutes=5)  # started 5 min ago, still has 10 min left
    df = _make_15m_df(last_candle_start, [100, 101, 102])
    monkeypatch.setattr(fetcher, "_download", lambda ticker, period, interval, retries=2: df)

    result = fetcher.get_last_completed_candle("NIFTY", "15m")

    assert result["is_completed"] is True
    # Must use the SECOND-to-last row (the last genuinely completed candle),
    # not the still-forming last one -- this is the core of the fix.
    assert result["close"] == 101.0
