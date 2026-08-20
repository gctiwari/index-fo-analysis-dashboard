"""
Direct tests of get_last_completed_candle() -- confirms completeness detection
works correctly (the core of the Step F entry-confirmation fix).
"""
import sys
sys.path.insert(0, ".")
import pandas as pd
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
import app.data.fetcher as fetcher

def make_15m_df(last_candle_start_ist, closes):
    """Builds a 15m OHLCV df ending at last_candle_start_ist with the given closes."""
    n = len(closes)
    starts = [last_candle_start_ist - timedelta(minutes=15*(n-1-i)) for i in range(n)]
    idx = pd.DatetimeIndex(starts)
    df = pd.DataFrame({
        "open": closes, "high": [c+1 for c in closes], "low": [c-1 for c in closes],
        "close": closes, "volume": [0]*n,
    }, index=idx)
    return df

# --- Test 1: last candle's period has FULLY elapsed -> should be treated as completed ---
now = datetime.now(IST)
last_candle_start = now - timedelta(minutes=20)  # started 20 min ago, 15m period ended 5 min ago
df = make_15m_df(last_candle_start, [100, 101, 102])
fetcher._download = lambda ticker, period, interval, retries=2: df
result = fetcher.get_last_completed_candle("NIFTY", "15m")
assert result["is_completed"] is True, result
assert result["close"] == 102, result
print("Test 1 (fully elapsed candle) PASSED:", result)

# --- Test 2: last candle is STILL FORMING -> should fall back to the previous (completed) one ---
last_candle_start = now - timedelta(minutes=5)  # started 5 min ago, still has 10 min left
df = make_15m_df(last_candle_start, [100, 101, 102])
fetcher._download = lambda ticker, period, interval, retries=2: df
result = fetcher.get_last_completed_candle("NIFTY", "15m")
assert result["is_completed"] is True, result
assert result["close"] == 101, result  # the SECOND-to-last row, not the still-forming last one
print("Test 2 (incomplete candle -> uses previous completed one) PASSED:", result)

print("\nALL CANDLE-COMPLETENESS TESTS PASSED")
