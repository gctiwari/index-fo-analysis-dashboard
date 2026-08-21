"""
Step 13's exact 5 scenarios, run against the real monitor_tick() function.
"""
import sys, numpy as np, pandas as pd
from datetime import datetime, timedelta
import pytz
sys.path.insert(0, ".")
IST = pytz.timezone("Asia/Kolkata")

# ---- Set up a minimal daily df so generate_daily_recommendations can build indicators/levels ----
def make_daily_df(n=300, base=100.0, seed=1):
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    ret = np.random.normal(0.0002, 0.004, n)
    close = base * np.exp(np.cumsum(ret))
    high = close * 1.003
    low = close * 0.997
    open_ = close
    vol = np.zeros(n)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=dates)
    df.index.name = "datetime"
    return df

import app.data.fetcher as fetcher
import app.services.tracker as trkmod
from app.db import Base, engine, SessionLocal
from app.models_db import Recommendation, PaperTrade

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

def make_rec(db, option_type, trigger, stop, cmp=100.0):
    from app.services.market_hours import today_ist
    rec = Recommendation(
        index_key="NIFTY", trade_date=today_ist(), role="PRIMARY", status="PENDING",
        direction="Bullish" if option_type == "CALL" else "Bearish", option_type=option_type,
        strike=round(trigger), expiry=(today_ist() + timedelta(days=7)).isoformat(), lot_size=75,
        cmp_at_generation=cmp, premium_at_generation=50.0, entry_type="Conditional",
        entry_trigger_desc=f"Enter on a 15-min close beyond {trigger}", entry_trigger_index_level=trigger,
        target_index_1=trigger + 10, target_index_2=trigger + 20, target_index_3=trigger + 30,
        stop_index_level=stop, target_premium_1=60.0, target_premium_2=70.0, target_premium_3=80.0,
        stop_premium=30.0, atr_pct_at_generation=1.0, confidence_score=65.0, reasoning="test",
    )
    db.add(rec); db.commit(); db.refresh(rec)
    return rec

def fifteen_min_df(closes):
    now = datetime.now(IST)
    n = len(closes)
    # Make the LAST candle fully elapsed (started 20 min ago) so it's always treated as completed in these tests.
    starts = [now - timedelta(minutes=20) - timedelta(minutes=15*(n-1-i)) for i in range(n)]
    idx = pd.DatetimeIndex(starts)
    return pd.DataFrame({"open": closes, "high": [c+0.5 for c in closes], "low": [c-0.5 for c in closes],
                          "close": closes, "volume": [0]*n}, index=idx)

# ============ Scenario 1: Trigger never reached ============
reset_db()
db = SessionLocal()
rec = make_rec(db, "CALL", trigger=105, stop=95, cmp=100)
fetcher.get_last_completed_candle = lambda idx, tf="15m": {"close": 103.0, "candle_start": None, "is_completed": True, "source": "completed_15m_close"}
fetcher.get_last_price = lambda idx: 103.0
trkmod.get_last_completed_candle = fetcher.get_last_completed_candle
trkmod.get_last_price = fetcher.get_last_price
trkmod.monitor_tick(db, "NIFTY")
db.refresh(rec)
assert rec.status == "PENDING", f"Scenario 1 FAILED: expected still PENDING (not yet EOD), got {rec.status}"
trkmod.finalize_day(db, "NIFTY")
db.refresh(rec)
assert rec.status == "NOT_EXECUTED", f"Scenario 1 FAILED: expected NOT_EXECUTED after finalize, got {rec.status}"
print("Scenario 1 (trigger never reached) PASSED -> NOT_EXECUTED")
db.close()

# ============ Scenario 2: Trigger reached intrabar but 15m CLOSE condition not met ============
reset_db()
db = SessionLocal()
rec = make_rec(db, "CALL", trigger=105, stop=95, cmp=100)
# Completed candle CLOSED at 104 (below trigger), even though intrabar high might have poked above 105.
fetcher.get_last_completed_candle = lambda idx, tf="15m": {"close": 104.0, "candle_start": None, "is_completed": True, "source": "completed_15m_close"}
fetcher.get_last_price = lambda idx: 104.0
trkmod.get_last_completed_candle = fetcher.get_last_completed_candle
trkmod.get_last_price = fetcher.get_last_price
trkmod.monitor_tick(db, "NIFTY")
db.refresh(rec)
assert rec.status == "PENDING", f"Scenario 2 FAILED: expected PENDING (close didn't confirm), got {rec.status}"
print("Scenario 2 (trigger touched intrabar, 15m close doesn't confirm) PASSED -> still PENDING, not executed")
db.close()

# ============ Scenario 3: Valid confirmation (CALL) ============
reset_db()
db = SessionLocal()
rec = make_rec(db, "CALL", trigger=105, stop=95, cmp=100)
fetcher.get_last_completed_candle = lambda idx, tf="15m": {"close": 106.0, "candle_start": None, "is_completed": True, "source": "completed_15m_close"}
fetcher.get_last_price = lambda idx: 106.0
trkmod.get_last_completed_candle = fetcher.get_last_completed_candle
trkmod.get_last_price = fetcher.get_last_price
trkmod.monitor_tick(db, "NIFTY")
db.refresh(rec)
assert rec.status == "EXECUTED", f"Scenario 3 FAILED: expected EXECUTED, got {rec.status}"
print("Scenario 3 (valid 15m close confirmation, CALL) PASSED -> EXECUTED")
db.close()

# ============ Scenario 4: PUT confirmation ============
reset_db()
db = SessionLocal()
rec = make_rec(db, "PUT", trigger=95, stop=105, cmp=100)
fetcher.get_last_completed_candle = lambda idx, tf="15m": {"close": 94.0, "candle_start": None, "is_completed": True, "source": "completed_15m_close"}
fetcher.get_last_price = lambda idx: 94.0
trkmod.get_last_completed_candle = fetcher.get_last_completed_candle
trkmod.get_last_price = fetcher.get_last_price
trkmod.monitor_tick(db, "NIFTY")
db.refresh(rec)
assert rec.status == "EXECUTED", f"Scenario 4 FAILED: expected EXECUTED, got {rec.status}"
print("Scenario 4 (PUT confirmation) PASSED -> EXECUTED")
db.close()

# ============ Scenario 5: Trigger reached only AFTER setup invalidation ============
reset_db()
db = SessionLocal()
rec = make_rec(db, "CALL", trigger=105, stop=95, cmp=100)
# First tick: price closes at 94, THROUGH the stop (95) -- setup invalidated before ever triggering.
fetcher.get_last_completed_candle = lambda idx, tf="15m": {"close": 94.0, "candle_start": None, "is_completed": True, "source": "completed_15m_close"}
fetcher.get_last_price = lambda idx: 94.0
trkmod.get_last_completed_candle = fetcher.get_last_completed_candle
trkmod.get_last_price = fetcher.get_last_price
trkmod.monitor_tick(db, "NIFTY")
db.refresh(rec)
assert rec.status == "INVALIDATED", f"Scenario 5 step A FAILED: expected INVALIDATED, got {rec.status}"
print("Scenario 5a (price breaks stop before ever triggering) PASSED -> INVALIDATED,", rec.invalidated_reason[:80])

# Second tick: price now closes above the ORIGINAL trigger (105) -- should NOT flip back to EXECUTED.
fetcher.get_last_completed_candle = lambda idx, tf="15m": {"close": 110.0, "candle_start": None, "is_completed": True, "source": "completed_15m_close"}
fetcher.get_last_price = lambda idx: 110.0
trkmod.get_last_completed_candle = fetcher.get_last_completed_candle
trkmod.get_last_price = fetcher.get_last_price
trkmod.monitor_tick(db, "NIFTY")
db.refresh(rec)
assert rec.status == "INVALIDATED", f"Scenario 5 step B FAILED: expected to STAY INVALIDATED (not late-execute), got {rec.status}"
print("Scenario 5b (later crossing the old trigger does NOT late-execute) PASSED -> still INVALIDATED, not EXECUTED")
db.close()

print("\n\nALL 5 STEP-13 SCENARIOS PASSED")
