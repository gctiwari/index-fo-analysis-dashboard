"""
Pure pandas/numpy indicator implementations -- no TA-Lib dependency (it needs
a compiled C library that isn't reliably pip-installable everywhere).
All functions take a DataFrame with columns open/high/low/close/volume
and a datetime index, and return either a Series or a scalar snapshot.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def stoch_rsi(series: pd.Series, period: int = 14, k_smooth: int = 3, d_smooth: int = 3):
    r = rsi(series, period)
    lowest = r.rolling(period).min()
    highest = r.rolling(period).max()
    raw_k = ((r - lowest) / (highest - lowest).replace(0, np.nan)) * 100
    k = raw_k.rolling(k_smooth).mean().fillna(50)
    d = k.rolling(d_smooth).mean().fillna(50)
    return k, d


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = true_range(df)
    atr_sm = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_sm.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_sm.replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def roc(series: pd.Series, period: int = 10) -> pd.Series:
    return ((series - series.shift(period)) / series.shift(period)) * 100


def bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = sma(series, period)
    std = series.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid.replace(0, np.nan)
    width_pctile = width.rolling(100, min_periods=20).rank(pct=True) * 100
    return upper, mid, lower, width_pctile.fillna(50)


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Volume-weighted average price per session. Yahoo Finance frequently reports
    zero volume for pure index tickers (^NSEI, ^NSEBANK, ^BSESN aren't directly
    traded instruments, unlike their constituent stocks or futures). When that
    happens the true VWAP formula divides by zero and, with volume at zero for
    every row, there's nothing left to backfill from -- it stays NaN, which
    then breaks JSON serialization downstream. Fall back to the session's
    cumulative average typical price in that case so this is always a real number.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.date
    vol = df["volume"].fillna(0)
    cum_vol = vol.groupby(day).cumsum()
    cum_vol_price = (typical * vol).groupby(day).cumsum()
    raw_vwap = cum_vol_price / cum_vol.replace(0, np.nan)

    day_count = typical.groupby(day).cumcount() + 1
    cum_typical = typical.groupby(day).cumsum()
    fallback = cum_typical / day_count

    vwap = raw_vwap.where(raw_vwap.notna(), fallback)
    return vwap.bfill().ffill()


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def volume_spike(df: pd.DataFrame, lookback: int = 20, multiple: float = 1.8) -> bool:
    if len(df) < lookback + 1:
        return False
    avg_vol = df["volume"].iloc[-lookback - 1:-1].mean()
    return bool(df["volume"].iloc[-1] > avg_vol * multiple)


def _safe(value: float, default: float = 0.0, decimals: int = 2) -> float:
    """Round a computed indicator value, substituting `default` for NaN/Inf so a
    single edge-case calculation (e.g. a flat-price instrument, a very short
    history window) can never produce a value that breaks JSON serialization
    or crashes the frontend, which expects real numbers here, not null."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return round(v, decimals)


def build_indicator_snapshot(df: pd.DataFrame) -> dict:
    close = df["close"]
    last_close = float(close.iloc[-1]) if not pd.isna(close.iloc[-1]) else 0.0
    macd_line, macd_signal, macd_hist = macd(close)
    k, d = stoch_rsi(close)
    upper, mid, lower, width_pctile = bollinger_bands(close)
    atr_series = atr(df)
    vwap_series = session_vwap(df)
    obv_series = obv(df)
    obv_mean_prev = obv_series.iloc[-6:-1].mean()
    obv_trend = "rising" if _safe(obv_series.iloc[-1]) > _safe(obv_mean_prev) else "falling"

    last = -1
    atr_last = _safe(atr_series.iloc[last])
    return {
        "rsi_14": _safe(rsi(close).iloc[last], default=50.0),
        "macd": _safe(macd_line.iloc[last]),
        "macd_signal": _safe(macd_signal.iloc[last]),
        "macd_hist": _safe(macd_hist.iloc[last]),
        "stoch_rsi_k": _safe(k.iloc[last], default=50.0),
        "stoch_rsi_d": _safe(d.iloc[last], default=50.0),
        "adx_14": _safe(adx(df).iloc[last]),
        "roc_10": _safe(roc(close).iloc[last]),
        "atr_14": atr_last,
        "atr_pct": _safe(atr_series.iloc[last] / last_close * 100) if last_close else 0.0,
        "bb_upper": _safe(upper.iloc[last], default=last_close),
        "bb_middle": _safe(mid.iloc[last], default=last_close),
        "bb_lower": _safe(lower.iloc[last], default=last_close),
        "bb_width_pctile": _safe(width_pctile.iloc[last], default=50.0, decimals=1),
        "ema_9": _safe(ema(close, 9).iloc[last], default=last_close),
        "ema_20": _safe(ema(close, 20).iloc[last], default=last_close),
        "ema_50": _safe(ema(close, 50).iloc[last], default=last_close),
        "ema_200": _safe(
            (ema(close, 200) if len(df) >= 200 else ema(close, len(df))).iloc[last], default=last_close
        ),
        "sma_20": _safe(sma(close, 20).iloc[last], default=last_close),
        "sma_50": _safe(
            (sma(close, 50) if len(df) >= 50 else sma(close, len(df))).iloc[last], default=last_close
        ),
        "vwap": _safe(vwap_series.iloc[last], default=last_close),
        "obv_slope": obv_trend,
        "volume_spike": volume_spike(df),
    }
