"""
Shared pytest fixtures for the whole test suite.

Design goals (per the follow-up audit):
  - Every test gets a completely fresh, isolated database (in-memory SQLite,
    created and torn down per test) -- tests never depend on execution
    order and never leak state into each other or into the real tracking.db.
  - Market data (candles, live price) is mocked deterministically via
    monkeypatch, never touching the real network.
  - Reusable factories for building Recommendation rows so each test file
    doesn't repeat the same 15-field constructor call.
"""
from __future__ import annotations
import os
import sys
from datetime import datetime, timedelta, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Make sure "app" is importable regardless of the directory pytest is invoked
# from -- pytest.ini's `pythonpath = .` already does this when the ini file
# is found, but this is a harmless, explicit belt-and-suspenders fallback.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.db import Base
from app import models_db  # noqa: F401 -- registers ORM models on Base.metadata
from app.models_db import Recommendation
from app.services.market_hours import today_ist, IST


@pytest.fixture()
def db_session():
    """A fresh, isolated in-memory SQLite database for every single test.
    Nothing here ever touches the real tracking.db file, and nothing
    persists between tests -- each test starts from a genuinely empty DB."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # critical for in-memory SQLite: without this, each checked-out
        # connection from the pool gets its OWN separate, empty in-memory database, causing
        # "no such table" errors as soon as more than one connection is used (e.g. by a FastAPI
        # TestClient request running through the dependency-injected session). StaticPool forces
        # every connection from this engine to share the single real in-memory database.
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session, monkeypatch):
    """A FastAPI TestClient wired to the SAME isolated in-memory db_session
    via dependency override (so API-level tests use the identical isolated
    DB as ORM-level tests), with the background scheduler disabled so tests
    never start a real APScheduler thread or hit the network on startup."""
    import app.scheduler as sched_mod
    monkeypatch.setattr(sched_mod, "start_scheduler", lambda: None)

    from app.main import app
    from app.db import get_db

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_15m_df(last_candle_start_ist: datetime, closes: list[float]):
    """Builds a synthetic 15-minute OHLCV DataFrame ending at last_candle_start_ist."""
    import pandas as pd
    n = len(closes)
    starts = [last_candle_start_ist - timedelta(minutes=15 * (n - 1 - i)) for i in range(n)]
    idx = pd.DatetimeIndex(starts)
    return pd.DataFrame({
        "open": closes, "high": [c + 0.5 for c in closes], "low": [c - 0.5 for c in closes],
        "close": closes, "volume": [0] * n,
    }, index=idx)


def make_daily_df(n=300, base=22000.0, drift=0.0004, seed=1):
    """Builds a synthetic daily OHLCV DataFrame, enough history for indicators/levels/patterns."""
    import numpy as np
    import pandas as pd
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    ret = rng.normal(drift, 0.006, n)
    close = base * np.exp(np.cumsum(ret))
    high = close * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.003, n)))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    vol = np.zeros(n)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=dates)
    df.index.name = "datetime"
    return df


@pytest.fixture()
def mock_completed_candle(monkeypatch):
    """
    Lets a test control exactly what get_last_completed_candle() and
    get_last_price() return, on every module that imported them by name
    (app.data.fetcher, app.services.tracker). Call the returned setter with
    a close price (and optionally is_completed=False) to change what the
    NEXT monitor_tick() call sees.
    """
    state = {"close": 100.0, "is_completed": True, "candle_start": None}

    def _candle(index_key: str, timeframe: str = "15m") -> dict:
        return {
            "close": state["close"],
            "candle_start": state["candle_start"] or datetime.now(IST),
            "is_completed": state["is_completed"],
            "source": "completed_15m_close" if state["is_completed"] else "incomplete_15m_fallback",
        }

    def _price(index_key: str) -> float:
        return state["close"]

    import app.data.fetcher as fetcher_mod
    import app.services.tracker as tracker_mod
    for mod in (fetcher_mod, tracker_mod):
        monkeypatch.setattr(mod, "get_last_completed_candle", _candle, raising=False)
        monkeypatch.setattr(mod, "get_last_price", _price, raising=False)

    def _set(close: float, is_completed: bool = True, candle_start: datetime | None = None):
        state["close"] = close
        state["is_completed"] = is_completed
        state["candle_start"] = candle_start

    _set.state = state
    return _set


@pytest.fixture()
def mock_daily_data(monkeypatch):
    """Patches get_ohlcv AND get_last_price everywhere they're imported (tracker.py and
    routes.py) to return internally-consistent, realistic-scale synthetic data. Deliberately
    does NOT combine with mock_completed_candle's tiny round-number price mocking (100/105/95)
    -- an earlier version of this fixture did, and it caused a real, reproducible crash:
    get_last_price() returning ~100 while ATR was computed from realistic ~25,000+ index-scale
    daily data made a PUT's target level go negative (target = cmp - 1.5x ATR, with ATR itself
    a few hundred points -- fine at real index scale, nonsensical against a mocked cmp of 100).
    That was a test-fixture scale mismatch, not a production bug: real ATR is never within two
    orders of magnitude of a real index's price. Keeping get_last_price consistent with the same
    daily data used for indicators avoids ever reintroducing that mismatch."""
    cache: dict[tuple[str, str], object] = {}

    def _fake_get_ohlcv(index_key: str, timeframe: str):
        n_map = {"1wk": 150, "1d": 300, "4h": 200, "1h": 200, "15m": 300}
        base_map = {"NIFTY": 25800.0, "BANKNIFTY": 57000.0, "SENSEX": 84500.0}
        key = (index_key, timeframe)
        if key not in cache:
            # Fixed, stable seed per (index, timeframe) -- NOT Python's built-in hash(), which is
            # randomized per-process by default (PYTHONHASHSEED) and would make this fixture's
            # data non-deterministic across test runs despite the "seed=" naming suggesting otherwise.
            seed = (abs(_stable_hash(key)) % 1000) + 1
            cache[key] = make_daily_df(n_map.get(timeframe, 300), base=base_map.get(index_key, 22000.0), seed=seed)
        return cache[key]

    def _fake_get_last_price(index_key: str) -> float:
        return float(_fake_get_ohlcv(index_key, "1d")["close"].iloc[-1])

    import app.data.fetcher as fetcher_mod
    import app.services.tracker as tracker_mod
    monkeypatch.setattr(fetcher_mod, "get_ohlcv", _fake_get_ohlcv, raising=False)
    monkeypatch.setattr(fetcher_mod, "get_last_price", _fake_get_last_price, raising=False)
    monkeypatch.setattr(tracker_mod, "get_ohlcv", _fake_get_ohlcv, raising=False)
    monkeypatch.setattr(tracker_mod, "get_last_price", _fake_get_last_price, raising=False)
    try:
        import app.api.routes as routes_mod
        monkeypatch.setattr(routes_mod, "get_ohlcv", _fake_get_ohlcv, raising=False)
    except ImportError:
        pass
    return _fake_get_ohlcv


def _stable_hash(key: tuple) -> int:
    import hashlib
    return int(hashlib.md5(str(key).encode()).hexdigest(), 16)


def make_recommendation(db_session, **overrides) -> Recommendation:
    """Factory for a PENDING PRIMARY Recommendation with sensible defaults, so individual
    tests only need to specify the fields that matter for what they're checking.

    Premiums are computed via the REAL estimate_premium() (Black-Scholes) function at
    each index level, not arbitrary round numbers -- using made-up premium values that
    don't match what the app's own pricing model would compute for the same strike/spot
    caused a real bug during development here: a stop_premium picked without reference to
    the actual pricing curve came out HIGHER than the freshly-computed entry premium,
    which made every trade "stop out" on the same tick it executed. Deriving all premiums
    from the same function the app uses keeps the fixture internally consistent by
    construction, regardless of the specific numbers chosen for strike/dte/atr_pct.
    """
    from app.analysis.trades import estimate_premium

    strike = overrides.get("strike", 105.0)
    option_type = overrides.get("option_type", "CALL")
    entry_trigger_index_level = overrides.get("entry_trigger_index_level", 105.0)
    stop_index_level = overrides.get("stop_index_level", 95.0)
    target_index_1 = overrides.get("target_index_1", 115.0)
    target_index_2 = overrides.get("target_index_2", 125.0)
    target_index_3 = overrides.get("target_index_3", 135.0)
    dte = 7

    defaults = dict(
        index_key="NIFTY", trade_date=today_ist(), role="PRIMARY", status="PENDING",
        direction="Bullish" if option_type == "CALL" else "Bearish", option_type=option_type,
        strike=strike, expiry=(today_ist() + timedelta(days=dte)).isoformat(), lot_size=75,
        cmp_at_generation=100.0, entry_type="Conditional",
        entry_trigger_desc=f"Enter on a 15-min close beyond {entry_trigger_index_level}",
        entry_trigger_index_level=entry_trigger_index_level,
        target_index_1=target_index_1, target_index_2=target_index_2, target_index_3=target_index_3,
        stop_index_level=stop_index_level,
        atr_pct_at_generation=1.0, confidence_score=65.0, reasoning="test fixture",
    )
    atr_pct = overrides.get("atr_pct_at_generation", defaults["atr_pct_at_generation"])
    defaults["premium_at_generation"] = round(estimate_premium(defaults["cmp_at_generation"], strike, dte, atr_pct, option_type), 1)
    defaults["stop_premium"] = round(estimate_premium(stop_index_level, strike, dte, atr_pct, option_type), 1)
    defaults["target_premium_1"] = round(estimate_premium(target_index_1, strike, dte, atr_pct, option_type), 1)
    defaults["target_premium_2"] = round(estimate_premium(target_index_2, strike, dte, atr_pct, option_type), 1)
    defaults["target_premium_3"] = round(estimate_premium(target_index_3, strike, dte, atr_pct, option_type), 1)

    defaults.update(overrides)
    rec = Recommendation(**defaults)
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)
    return rec
