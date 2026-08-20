"""
Candlestick pattern recognition (rule-based, last-N candles) and a
simplified chart-pattern detector built on swing-point pivots.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def _body(row) -> float:
    return abs(row["close"] - row["open"])


def _range(row) -> float:
    return max(row["high"] - row["low"], 1e-9)


def _upper_wick(row) -> float:
    return row["high"] - max(row["close"], row["open"])


def _lower_wick(row) -> float:
    return min(row["close"], row["open"]) - row["low"]


def detect_candlesticks(df: pd.DataFrame, timeframe: str, lookback: int = 5) -> list[dict]:
    """Scan the last `lookback` candles for classic single/multi-candle patterns."""
    out: list[dict] = []
    if len(df) < 3:
        return out
    window = df.iloc[-lookback:]

    for i in range(len(window)):
        idx = window.index[i]
        row = window.iloc[i]
        body, rng = _body(row), _range(row)
        upper, lower = _upper_wick(row), _lower_wick(row)
        bullish = row["close"] > row["open"]

        # Doji
        if body / rng < 0.08:
            out.append(_p("Doji", "candlestick", "neutral", timeframe, 0.55, idx,
                          "Open and close nearly equal; indecision between buyers and sellers."))
        # Marubozu
        elif body / rng > 0.9:
            direction = "bullish" if bullish else "bearish"
            out.append(_p("Bullish Marubozu" if bullish else "Bearish Marubozu", "candlestick",
                          direction, timeframe, 0.65, idx,
                          "Little to no wick; strong conviction in the closing direction."))
        # Hammer / Inverted Hammer (bottom of a move)
        elif lower > 2 * body and upper < body * 0.6:
            out.append(_p("Hammer", "candlestick", "bullish", timeframe, 0.6, idx,
                          "Long lower wick rejecting lower prices; potential bullish reversal if at support."))
        elif upper > 2 * body and lower < body * 0.6:
            out.append(_p("Inverted Hammer / Shooting Star", "candlestick",
                          "bullish" if bullish else "bearish", timeframe, 0.55, idx,
                          "Long upper wick; context (top or bottom of move) determines interpretation."))
        # Spinning top
        elif 0.08 <= body / rng <= 0.3 and upper > body and lower > body:
            out.append(_p("Spinning Top", "candlestick", "neutral", timeframe, 0.45, idx,
                          "Small body with wicks on both sides; momentum stalling."))

        # Two-candle patterns
        if i >= 1:
            prev = window.iloc[i - 1]
            prev_bullish = prev["close"] > prev["open"]
            prev_body = _body(prev)
            # Engulfing
            if bullish and not prev_bullish and row["close"] > prev["open"] and row["open"] < prev["close"] and body > prev_body:
                out.append(_p("Bullish Engulfing", "candlestick", "bullish", timeframe, 0.7, idx,
                              "Current candle's body fully engulfs the prior bearish candle."))
            elif not bullish and prev_bullish and row["open"] > prev["close"] and row["close"] < prev["open"] and body > prev_body:
                out.append(_p("Bearish Engulfing", "candlestick", "bearish", timeframe, 0.7, idx,
                              "Current candle's body fully engulfs the prior bullish candle."))
            # Piercing line / Dark cloud cover
            elif bullish and not prev_bullish and row["open"] < prev["low"] and row["close"] > (prev["open"] + prev["close"]) / 2:
                out.append(_p("Piercing Line", "candlestick", "bullish", timeframe, 0.6, idx,
                              "Gaps down then closes above the midpoint of the prior bearish candle."))
            elif not bullish and prev_bullish and row["open"] > prev["high"] and row["close"] < (prev["open"] + prev["close"]) / 2:
                out.append(_p("Dark Cloud Cover", "candlestick", "bearish", timeframe, 0.6, idx,
                              "Gaps up then closes below the midpoint of the prior bullish candle."))
            # Harami
            elif body < prev_body * 0.6 and row["high"] < prev["high"] and row["low"] > prev["low"]:
                direction = "bullish" if bullish else "bearish"
                out.append(_p("Harami", "candlestick", direction, timeframe, 0.5, idx,
                              "Small body contained within the prior candle's range; potential trend pause."))

        # Three-candle patterns
        if i >= 2:
            c1, c2, c3 = window.iloc[i - 2], window.iloc[i - 1], row
            c1_bear, c3_bull = c1["close"] < c1["open"], c3["close"] > c3["open"]
            c1_bull, c3_bear = c1["close"] > c1["open"], c3["close"] < c3["open"]
            small_mid = _body(c2) < _body(c1) * 0.5
            if c1_bear and small_mid and c3_bull and c3["close"] > (c1["open"] + c1["close"]) / 2:
                out.append(_p("Morning Star", "candlestick", "bullish", timeframe, 0.72, idx,
                              "Down candle, small-bodied indecision candle, then a strong up candle -- classic bottom reversal."))
            elif c1_bull and small_mid and c3_bear and c3["close"] < (c1["open"] + c1["close"]) / 2:
                out.append(_p("Evening Star", "candlestick", "bearish", timeframe, 0.72, idx,
                              "Up candle, small-bodied indecision candle, then a strong down candle -- classic top reversal."))
            elif c1_bull and c2["close"] > c2["open"] and c3_bull and c1["close"] < c2["close"] < c3["close"]:
                out.append(_p("Three White Soldiers", "candlestick", "bullish", timeframe, 0.68, idx,
                              "Three consecutive strong bullish candles with higher closes."))
            elif c1_bear and c2["close"] < c2["open"] and c3_bear and c1["close"] > c2["close"] > c3["close"]:
                out.append(_p("Three Black Crows", "candlestick", "bearish", timeframe, 0.68, idx,
                              "Three consecutive strong bearish candles with lower closes."))

    # De-duplicate by name, keep most recent + highest confidence
    dedup: dict[str, dict] = {}
    for p in out:
        key = p["name"]
        if key not in dedup or p["confidence"] >= dedup[key]["confidence"]:
            dedup[key] = p
    return list(dedup.values())


def _p(name, category, direction, timeframe, confidence, idx, note) -> dict:
    return {
        "name": name, "category": category, "direction": direction,
        "timeframe": timeframe, "confidence": confidence,
        "note": f"{note} (formed {idx.strftime('%d-%b %H:%M') if hasattr(idx, 'strftime') else idx})",
    }


def swing_points(df: pd.DataFrame, order: int = 5) -> tuple[pd.Series, pd.Series]:
    highs = df["high"].values
    lows = df["low"].values
    hi_idx = argrelextrema(highs, np.greater_equal, order=order)[0]
    lo_idx = argrelextrema(lows, np.less_equal, order=order)[0]
    swing_highs = df["high"].iloc[hi_idx]
    swing_lows = df["low"].iloc[lo_idx]
    return swing_highs, swing_lows


def detect_chart_patterns(df: pd.DataFrame, timeframe: str) -> list[dict]:
    """Simplified structural detection: double top/bottom and triangle-ish compression."""
    out: list[dict] = []
    if len(df) < 30:
        return out
    swing_highs, swing_lows = swing_points(df, order=4)

    # Double top: two comparable swing highs within 0.5% with a trough between them
    if len(swing_highs) >= 2:
        h = swing_highs.tail(2)
        if abs(h.iloc[0] - h.iloc[1]) / h.iloc[0] < 0.006:
            out.append({
                "name": "Double Top", "category": "chart", "direction": "bearish",
                "timeframe": timeframe, "confidence": 0.55,
                "note": f"Two swing highs near {h.iloc[1]:.0f} -- watch for a break below the intervening trough to confirm.",
            })
    if len(swing_lows) >= 2:
        lo = swing_lows.tail(2)
        if abs(lo.iloc[0] - lo.iloc[1]) / lo.iloc[0] < 0.006:
            out.append({
                "name": "Double Bottom", "category": "chart", "direction": "bullish",
                "timeframe": timeframe, "confidence": 0.55,
                "note": f"Two swing lows near {lo.iloc[1]:.0f} -- watch for a break above the intervening peak to confirm.",
            })

    # Volatility compression -> triangle/flag context (paired with BB width elsewhere)
    recent_range = df["high"].tail(15).max() - df["low"].tail(15).min()
    prior_range = df["high"].iloc[-40:-15].max() - df["low"].iloc[-40:-15].min() if len(df) >= 40 else recent_range
    if prior_range > 0 and recent_range / prior_range < 0.55:
        out.append({
            "name": "Range Compression (Triangle/Flag Context)", "category": "chart", "direction": "neutral",
            "timeframe": timeframe, "confidence": 0.5,
            "note": "Recent trading range has contracted sharply versus the prior range -- often precedes a directional breakout.",
        })

    return out
