import sys, numpy as np, pandas as pd
from datetime import datetime, timedelta, date
import pytz
sys.path.insert(0, ".")
IST = pytz.timezone("Asia/Kolkata")

def make_df(n, freq, base, drift, seed):
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq=freq)
    ret = np.random.normal(drift, 0.006, n)
    close = base * np.exp(np.cumsum(ret))
    high = close * (1 + np.abs(np.random.normal(0, 0.003, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.003, n)))
    open_ = close * (1 + np.random.normal(0, 0.002, n))
    vol = np.zeros(n)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=dates)
    df.index.name = "datetime"
    return df

def make_15m(base, n=50):
    now = datetime.now(IST)
    starts = [now - timedelta(minutes=20) - timedelta(minutes=15*(n-1-i)) for i in range(n)]
    closes = base * (1 + np.random.normal(0, 0.001, n)).cumprod()
    idx = pd.DatetimeIndex(starts)
    return pd.DataFrame({"open": closes, "high": closes*1.001, "low": closes*0.999, "close": closes, "volume":[0]*n}, index=idx)

import app.data.fetcher as fetcher
_cached = {}
BASES = {"NIFTY": 25800, "BANKNIFTY": 57000, "SENSEX": 84500}
def fake_get_ohlcv(index_key, timeframe):
    n_map = {"1wk": 150, "1d": 300, "4h": 200, "1h": 200, "15m": 300}
    freq_map = {"1wk": "W", "1d": "B", "4h": "4h", "1h": "h", "15m": "15min"}
    key = (index_key, timeframe)
    if key not in _cached:
        if timeframe == "15m":
            _cached[key] = make_15m(BASES[index_key])
        else:
            _cached[key] = make_df(n_map[timeframe], freq_map[timeframe], BASES[index_key], 0.0003, seed=hash(index_key)%999)
    return _cached[key]
fetcher.get_ohlcv = fake_get_ohlcv
fetcher.get_last_price = lambda idx: float(fake_get_ohlcv(idx, "15m")["close"].iloc[-1])
fetcher.get_last_completed_candle = lambda idx, tf="15m": {"close": float(fake_get_ohlcv(idx, "15m")["close"].iloc[-1]), "candle_start": None, "is_completed": True, "source": "test"}

import app.api.routes as routes
routes.get_ohlcv = fake_get_ohlcv
import app.services.tracker as trkmod
trkmod.get_ohlcv = fake_get_ohlcv
trkmod.get_last_price = fetcher.get_last_price
trkmod.get_last_completed_candle = fetcher.get_last_completed_candle
import app.api.tracking_routes as trk_routes
import app.scheduler as sched_mod
sched_mod.start_scheduler = lambda: None

from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    # === Test 1: today's-trades XLSX export ===
    r = client.get("/api/export-today/xlsx")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(r.content) > 500
    print("Test 1 PASSED: today's-trades XLSX export -> 200, %d bytes, sheet generated" % len(r.content))

    # Verify content structure by reading it back with openpyxl
    import io, openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["Today's Trades"]
    headers = [c.value for c in ws[1]]
    print("   Columns:", headers)
    assert headers[:7] == ["Option Name", "Price", "Target 1", "Target 2", "Target 3", "Stop Loss", "Enter When"]
    print("   Column order matches exactly what was requested (Option Name/Price/Target/Stop Loss/Enter When)")
    row_count = ws.max_row - 1
    print("   Rows (trades):", row_count)
    assert row_count >= 1

    # === Test 2: yesterday endpoint, with NO prior-day data yet ===
    r2 = client.get("/api/tracking/NIFTY/yesterday")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["trade_date"] is None and d2["legs"] == []
    print("Test 2 PASSED: /yesterday with no prior data -> trade_date=None, legs=[] (honest, not fabricated)")

    # === Test 3: seed an actual PAST-dated recommendation manually, then verify /yesterday finds and settles it ===
    from app.db import SessionLocal
    from app.models_db import Recommendation, PaperTrade
    from app.services.market_hours import today_ist
    db = SessionLocal()
    yesterday_date = today_ist() - timedelta(days=1)
    rec = Recommendation(
        index_key="NIFTY", trade_date=yesterday_date, role="PRIMARY", status="PENDING",
        direction="Bullish", option_type="CALL", strike=25800, expiry=(today_ist()+timedelta(days=5)).isoformat(),
        lot_size=75, cmp_at_generation=25750, premium_at_generation=50.0, entry_type="Conditional",
        entry_trigger_desc="Enter on a 15-min close beyond 25800", entry_trigger_index_level=25800,
        target_index_1=25850, target_index_2=25900, target_index_3=25950, stop_index_level=25700,
        target_premium_1=60.0, target_premium_2=70.0, target_premium_3=80.0, stop_premium=30.0,
        atr_pct_at_generation=1.0, confidence_score=65.0, reasoning="test seed", monitor_tick_count=3,
    )
    db.add(rec); db.commit(); db.close()

    r3 = client.get("/api/tracking/NIFTY/yesterday")
    d3 = r3.json()
    assert d3["trade_date"] == yesterday_date.isoformat(), d3
    assert len(d3["legs"]) == 1
    leg = d3["legs"][0]
    # Should have been lazily finalized (was PENDING, day is over) -> NOT_EXECUTED
    assert leg["status"] == "NOT_EXECUTED", leg["status"]
    print("Test 3 PASSED: seeded a stale PENDING from yesterday -> /yesterday lazily finalized it to NOT_EXECUTED")
    print("   Reason:", leg["not_executed_reason"][:100])

    # === Test 4: seed an EXECUTED-and-CLOSED (profitable) trade for yesterday, verify P&L shows correctly ===
    db = SessionLocal()
    rec2 = Recommendation(
        index_key="BANKNIFTY", trade_date=yesterday_date, role="PRIMARY", status="EXECUTED",
        direction="Bullish", option_type="CALL", strike=57000, expiry=(today_ist()+timedelta(days=5)).isoformat(),
        lot_size=30, cmp_at_generation=56900, premium_at_generation=100.0, entry_type="Immediate",
        entry_trigger_desc="Immediate entry", entry_trigger_index_level=56900,
        target_index_1=57100, target_index_2=57200, target_index_3=57300, stop_index_level=56700,
        target_premium_1=130.0, target_premium_2=160.0, target_premium_3=190.0, stop_premium=70.0,
        atr_pct_at_generation=1.0, confidence_score=80.0, reasoning="test seed profitable",
    )
    db.add(rec2); db.commit(); db.refresh(rec2)
    trade = PaperTrade(
        recommendation_id=rec2.id, index_key="BANKNIFTY", trade_date=yesterday_date,
        entry_index_level=56900, entry_premium=100.0, entry_time=datetime.now(),
        exit_index_level=57150, exit_premium=135.0, exit_time=datetime.now(),
        mfe_premium=135.0, targets_hit=["target_1"], stop_hit=False, status="CLOSED", outcome="TARGET_1",
        pnl_rupees=(135.0-100.0)*30, pnl_pct=round((135.0-100.0)/100.0*100, 2),
    )
    db.add(trade); db.commit(); db.close()

    r4 = client.get("/api/tracking/BANKNIFTY/yesterday")
    d4 = r4.json()
    leg4 = d4["legs"][0]
    assert leg4["status"] == "EXECUTED"
    assert leg4["paper_trade"]["status"] == "CLOSED"
    assert leg4["paper_trade"]["pnl_pct"] == 35.0
    print("Test 4 PASSED: profitable executed trade from yesterday shows status=EXECUTED, outcome=TARGET_1, PnL=+35.0%%")
    print("   PnL Rs:", leg4["paper_trade"]["pnl_rupees"])

print("\n\nALL NEW-FEATURE TESTS PASSED")
