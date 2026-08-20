"""
Data access layer. Everything that talks to an external source lives here,
so swapping yfinance for a paid vendor (NSE option-chain, FII/DII, broker
feeds) later means editing this file only -- the analysis engine and API
never call yfinance directly.

IMPORTANT: Yahoo Finance now blocks plain-requests traffic (it returns an
HTML/block page instead of JSON, which surfaces in yfinance as "Expecting
value: line 1 column 1" or "possibly delisted"). yfinance's fix is to send
requests through curl_cffi with a browser-impersonation profile. We build
one shared impersonated session here and pass it to every yf.Ticker() call.
"""
from __future__ import annotations
import logging
import time
from functools import lru_cache
from datetime import datetime, timedelta

import pandas as pd
import pytz
import yfinance as yf
from curl_cffi import requests as curl_requests

from app.config import INDEX_REGISTRY, MACRO_TICKERS

logger = logging.getLogger("data.fetcher")
_IST = pytz.timezone("Asia/Kolkata")

# One shared, browser-impersonating session for every Yahoo Finance request.
# "chrome" is the safest cross-version choice; if curl_cffi complains a given
# profile (e.g. "chrome136") isn't supported, upgrade curl_cffi (pip install
# -U curl_cffi) or fall back to plain "chrome".
_SESSION = curl_requests.Session(impersonate="chrome")


class DataUnavailableError(Exception):
    pass


def _download(ticker: str, period: str, interval: str, retries: int = 2) -> pd.DataFrame:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            df = yf.Ticker(ticker, session=_SESSION).history(period=period, interval=interval, auto_adjust=False)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("yfinance error for %s (attempt %d/%d): %s", ticker, attempt + 1, retries + 1, exc)
            time.sleep(1.5 * (attempt + 1))  # simple backoff -- Yahoo rate-limits bursty requests
            continue
        if df is not None and not df.empty:
            df = df.rename(columns=str.lower)
            df.index.name = "datetime"
            return df[["open", "high", "low", "close", "volume"]]
        last_exc = DataUnavailableError(f"Empty response for {ticker} ({period}/{interval})")
        time.sleep(1.5 * (attempt + 1))
    raise DataUnavailableError(f"No data returned for {ticker} ({period}/{interval})") from last_exc


# Timeframe -> (yfinance period, yfinance interval)
TIMEFRAME_MAP = {
    "1mo": ("5y", "1mo"),
    "1wk": ("5y", "1wk"),
    "1d": ("2y", "1d"),
    "4h": ("60d", "1h"),   # yfinance has no native 4h; resampled from 1h below
    "1h": ("60d", "1h"),
    "30m": ("30d", "30m"),
    "15m": ("30d", "15m"),
    "5m": ("30d", "5m"),
}


def get_ohlcv(index_key: str, timeframe: str) -> pd.DataFrame:
    cfg = INDEX_REGISTRY.get(index_key)
    if cfg is None or not cfg.yf_ticker:
        raise DataUnavailableError(f"No live data source configured for '{index_key}' yet.")
    period, interval = TIMEFRAME_MAP[timeframe]
    df = _download(cfg.yf_ticker, period, interval)
    if timeframe == "4h":
        df = (
            df.resample("4h", origin="start_day")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna()
        )
    return df


def get_macro_snapshot() -> dict[str, dict]:
    """Best-effort snapshot of macro/correlation tickers. Missing or invalid ones are skipped, not fatal --
    a ticker is only included if it has a real, finite last price, so the frontend never has to handle a
    null numeric field for an entry that IS present (it just won't appear at all, same as a fetch failure)."""
    import math
    out: dict[str, dict] = {}
    for label, ticker in MACRO_TICKERS.items():
        try:
            df = _download(ticker, period="5d", interval="1d")
            last, prev = df.iloc[-1], df.iloc[-2]
            last_close, prev_close = float(last["close"]), float(prev["close"])
            if not (math.isfinite(last_close) and math.isfinite(prev_close)) or prev_close == 0:
                logger.warning("Macro fetch skipped for %s: non-finite or zero price data", label)
                continue
            chg = last_close - prev_close
            chg_pct = (chg / prev_close) * 100
            out[label] = {
                "ticker": ticker,
                "last": round(last_close, 2),
                "change": round(chg, 2),
                "change_pct": round(chg_pct, 2),
            }
        except DataUnavailableError as exc:
            logger.warning("Macro fetch skipped for %s: %s", label, exc)
    return out


def get_last_price(index_key: str) -> float:
    """Best-effort current price for intraday monitoring. Falls back to last daily close."""
    cfg = INDEX_REGISTRY.get(index_key)
    if cfg is None or not cfg.yf_ticker:
        raise DataUnavailableError(f"No live data source configured for '{index_key}' yet.")
    try:
        fast = yf.Ticker(cfg.yf_ticker, session=_SESSION).fast_info
        price = fast.get("last_price") or fast.get("lastPrice")
        if price:
            return float(price)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fast_info failed for %s: %s", cfg.yf_ticker, exc)
    df = _download(cfg.yf_ticker, period="5d", interval="15m")
    return float(df["close"].iloc[-1])


def get_last_completed_candle(index_key: str, timeframe: str = "15m") -> dict:
    """
    Returns the most recently COMPLETED candle for entry-confirmation checks
    -- i.e. NOT the still-forming current candle. This exists because trade
    triggers are worded as "enter on a 15-min close beyond X", which means
    exactly what it says: a candle has to have actually finished and closed
    past the level, not just touched it on a live tick.

    Returns {"close": float, "candle_start": datetime, "is_completed": bool,
    "source": str}. If completeness can't be determined confidently (e.g. an
    unexpected index dtype from yfinance), falls back to treating the last
    row as the reference point but flags is_completed=False so callers can
    decide how strict to be, rather than silently guessing.
    """
    cfg = INDEX_REGISTRY.get(index_key)
    if cfg is None or not cfg.yf_ticker:
        raise DataUnavailableError(f"No live data source configured for '{index_key}' yet.")
    period, interval = TIMEFRAME_MAP[timeframe]
    df = _download(cfg.yf_ticker, period, interval)

    interval_minutes = {"15m": 15, "5m": 5, "30m": 30, "1h": 60}.get(timeframe, 15)
    now = datetime.now(_IST)

    try:
        last_ts = df.index[-1]
        last_ts = last_ts.tz_localize(_IST) if last_ts.tzinfo is None else last_ts.tz_convert(_IST)
        candle_end = last_ts + timedelta(minutes=interval_minutes)
        if candle_end <= now:
            # Last row's period has already fully elapsed -- it's a real, completed candle.
            return {"close": float(df["close"].iloc[-1]), "candle_start": last_ts, "is_completed": True, "source": f"completed_{timeframe}_close"}
        if len(df) >= 2:
            # Last row is still forming; the one before it is the last genuinely completed candle.
            prev_ts = df.index[-2]
            prev_ts = prev_ts.tz_localize(_IST) if prev_ts.tzinfo is None else prev_ts.tz_convert(_IST)
            return {"close": float(df["close"].iloc[-2]), "candle_start": prev_ts, "is_completed": True, "source": f"completed_{timeframe}_close"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not determine candle completeness for %s %s: %s", index_key, timeframe, exc)

    # Fallback: couldn't confidently confirm completeness -- use the last row but say so honestly.
    return {"close": float(df["close"].iloc[-1]), "candle_start": None, "is_completed": False, "source": f"incomplete_{timeframe}_fallback"}


@lru_cache(maxsize=1)
def _cache_bust_key() -> str:
    # Cache is invalidated per-process-minute so repeated calls within the same
    # minute don't re-hit yfinance; replace with Redis for real deployments.
    return datetime.utcnow().strftime("%Y%m%d%H%M")
