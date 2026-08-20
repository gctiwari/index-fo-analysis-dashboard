from __future__ import annotations
import numpy as np
import pandas as pd

from app.analysis.patterns import swing_points
from app.analysis.indicators import adx


def trend_structure(df: pd.DataFrame, timeframe: str) -> dict:
    """Dow-theory style HH/HL vs LH/LL read from the last few swing points."""
    swing_highs, swing_lows = swing_points(df, order=3)
    direction, structure = "sideways", "No clear swing sequence yet"

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs.iloc[-1] > swing_highs.iloc[-2]
        hl = swing_lows.iloc[-1] > swing_lows.iloc[-2]
        lh = swing_highs.iloc[-1] < swing_highs.iloc[-2]
        ll = swing_lows.iloc[-1] < swing_lows.iloc[-2]
        if hh and hl:
            direction, structure = "uptrend", "Higher Highs & Higher Lows"
        elif lh and ll:
            direction, structure = "downtrend", "Lower Highs & Lower Lows"
        elif hh and ll:
            direction, structure = "sideways", "Expanding range (higher high, lower low) -- volatility rising"
        else:
            direction, structure = "sideways", "Contracting / mixed swings -- consolidation"

    adx_val = float(adx(df).iloc[-1])
    strength = min(100.0, round(adx_val * 2.2, 1))  # scale ADX(~0-40 typical) into a 0-100 strength read
    return {"timeframe": timeframe, "direction": direction, "structure": structure, "strength": strength}


def support_resistance(df: pd.DataFrame, n_levels: int = 3) -> dict:
    """
    Support/resistance selection, rewritten to fix a systemic bug: the
    previous version pooled swing highs/lows from up to 120 daily bars
    (~6 months) without checking whether a candidate was even on the
    correct side of current price, then picked the FARTHEST candidate by
    raw magnitude as the trade-trigger level (`max(resistance)` /
    `min(support)`), while other parts of the codebase assumed index [0]
    was the NEAREST level. Both bugs pushed trade triggers far from CMP.

    Fixed approach:
      1. Pull candidates from multiple, clearly-scoped horizons (near-term
         and medium-term swings, floor pivots, and round-number levels)
         instead of one long undifferentiated window.
      2. Filter every candidate by direction relative to CMP (resistance
         must be above price, support must be below) -- a stale swing
         point that price has since moved through is not a real level.
      3. Rank by DISTANCE from CMP, nearest first, for both lists -- so
         index [0] is always genuinely the nearest level, consistently.
      4. Expose `breakout`/`breakdown` as the nearest level ONLY if it
         (a) falls within a realistic band (not noise-close, not further
         than this app's own 3rd-target scale of ~2.3x ATR would reach),
         AND (b) has a genuine technical basis -- a floor pivot or an
         actual historical swing point. Round numbers are real (order
         flow does cluster there) but are used only as a CONFIDENCE BOOST
         when they coincide with a technical level, never as the sole
         basis for a trigger -- otherwise the near-ubiquity of round
         numbers (there's always one within a percent of any price) would
         let the system "always find something" even on a day with no
         real structure, which is exactly what was asked to be avoided.
         When nothing technical qualifies, breakout/breakdown are None
         and the trade generator correctly reports WAIT / NO TRADE.
    """
    last = df.iloc[-1]
    cmp = float(last["close"])
    pivot = (last["high"] + last["low"] + last["close"]) / 3
    r1, s1 = 2 * pivot - last["low"], 2 * pivot - last["high"]
    r2, s2 = pivot + (last["high"] - last["low"]), pivot - (last["high"] - last["low"])

    atr_val = float(_true_range_atr(df))
    round_step = _round_step_for(cmp)

    technical_candidates: set[float] = {round(r1, 1), round(r2, 1), round(s1, 1), round(s2, 1)}
    # Near-term swings: tight window, catches genuinely recent turning points.
    near_highs, near_lows = swing_points(df.tail(30), order=2)
    # Medium-term swings: wider window, but still a fraction of the old 120-bar span.
    mid_highs, mid_lows = swing_points(df.tail(60), order=4)
    for series in (near_highs, mid_highs):
        technical_candidates.update(round(float(x), 1) for x in series.tail(6))
    for series in (near_lows, mid_lows):
        technical_candidates.update(round(float(x), 1) for x in series.tail(6))

    # Round-number "psychological" levels -- real, but a confidence booster
    # only (see docstring), not an independent source of a trigger.
    base = round(cmp / round_step) * round_step
    round_candidates = {base, base + round_step, base - round_step, base + 2 * round_step, base - 2 * round_step}

    all_candidates = technical_candidates | round_candidates
    resistance_all = sorted((c for c in all_candidates if c > cmp), key=lambda x: x - cmp)
    support_all = sorted((c for c in all_candidates if c < cmp), key=lambda x: cmp - x)
    tech_resistance = sorted((c for c in technical_candidates if c > cmp), key=lambda x: x - cmp)
    tech_support = sorted((c for c in technical_candidates if c < cmp), key=lambda x: cmp - x)

    resistance = resistance_all[:n_levels]
    support = support_all[:n_levels]

    # Tradeable band for a trigger level: below ~0.35x ATR is noise (basically
    # already at CMP); above ~3.0x ATR exceeds this app's own 3rd-target reach
    # (t3 = level +/- 2.3x ATR elsewhere), i.e. not realistically actionable
    # for the multi-session holding window these trades are built around.
    min_band, max_band = atr_val * 0.35, atr_val * 3.0

    def _tradeable(full_sorted_list):
        """Only ever called with technical (pivot/swing) candidates -- see below."""
        for level in full_sorted_list:
            dist = abs(level - cmp)
            if dist < min_band:
                continue  # too close, keep scanning for a real level past the noise
            if dist > max_band:
                return None  # candidates are distance-sorted, so nothing closer qualifies either
            return level
        return None

    def _has_round_number_confluence(level: float | None) -> bool:
        if level is None:
            return False
        return any(abs(level - r) <= round_step * 0.15 for r in round_candidates)

    breakout = _tradeable(tech_resistance)
    breakdown = _tradeable(tech_support)

    return {
        "support": support,
        "resistance": resistance,
        "breakout": breakout,
        "breakdown": breakdown,
        "breakout_round_number_confluence": _has_round_number_confluence(breakout),
        "breakdown_round_number_confluence": _has_round_number_confluence(breakdown),
        "pivot": round(float(pivot), 1),
    }


def _true_range_atr(df: pd.DataFrame, period: int = 14) -> float:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    val = tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    return float(val) if pd.notna(val) and val > 0 else float(df["close"].iloc[-1]) * 0.005


def _round_step_for(cmp: float) -> float:
    """Psychological round-number step, scaled to the index's price magnitude."""
    if cmp >= 60000:
        return 500.0
    if cmp >= 20000:
        return 100.0
    if cmp >= 5000:
        return 50.0
    return 25.0


def gap_analysis(df: pd.DataFrame) -> dict | None:
    if len(df) < 2:
        return None
    prev_close = df["close"].iloc[-2]
    today_open = df["open"].iloc[-1]
    gap_pct = (today_open - prev_close) / prev_close * 100
    if abs(gap_pct) < 0.15:
        return None
    return {
        "type": "gap_up" if gap_pct > 0 else "gap_down",
        "gap_pct": round(float(gap_pct), 2),
        "prev_close": round(float(prev_close), 1),
        "open": round(float(today_open), 1),
    }
