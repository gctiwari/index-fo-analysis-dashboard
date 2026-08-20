"""
Deterministic rule engine that merges indicator, trend, pattern and level
signals into one directional read. Every factor is logged with its own
signal + weight so the output is auditable, not a black-box score.
"""
from __future__ import annotations
from app.config import INDEX_REGISTRY


def _factor(name, signal, weight, detail):
    return {"factor": name, "signal": signal, "weight": weight, "detail": detail}


def build_confluence(ind: dict, trends: list[dict], patterns: list[dict], levels: dict, cmp: float) -> dict:
    factors = []

    # --- Trend (daily is primary reference) ---
    daily = next((t for t in trends if t["timeframe"] == "1d"), trends[0] if trends else None)
    if daily:
        sig = "bullish" if daily["direction"] == "uptrend" else "bearish" if daily["direction"] == "downtrend" else "neutral"
        factors.append(_factor("Daily Trend Structure", sig, 3.0, f"{daily['structure']} (strength {daily['strength']}/100)"))

    # --- Higher-timeframe alignment ---
    weekly = next((t for t in trends if t["timeframe"] == "1wk"), None)
    if weekly and daily:
        aligned = weekly["direction"] == daily["direction"]
        factors.append(_factor(
            "Multi-Timeframe Alignment",
            "bullish" if aligned and daily["direction"] == "uptrend" else "bearish" if aligned and daily["direction"] == "downtrend" else "neutral",
            2.0,
            "Weekly and daily trend agree" if aligned else "Weekly and daily trend conflict -- lower conviction",
        ))

    # --- Moving averages (price vs EMA stack) ---
    ema_bull = cmp > ind["ema_20"] > ind["ema_50"]
    ema_bear = cmp < ind["ema_20"] < ind["ema_50"]
    factors.append(_factor(
        "EMA Stack (Price/20/50)",
        "bullish" if ema_bull else "bearish" if ema_bear else "neutral",
        2.0,
        f"CMP {cmp:.0f} vs EMA20 {ind['ema_20']:.0f} / EMA50 {ind['ema_50']:.0f}",
    ))

    # --- Momentum: RSI ---
    rsi = ind["rsi_14"]
    rsi_sig = "bullish" if rsi > 55 else "bearish" if rsi < 45 else "neutral"
    factors.append(_factor("RSI (14)", rsi_sig, 1.5, f"RSI at {rsi:.1f}"))

    # --- Momentum: MACD ---
    macd_sig = "bullish" if ind["macd_hist"] > 0 else "bearish" if ind["macd_hist"] < 0 else "neutral"
    factors.append(_factor("MACD Histogram", macd_sig, 1.5, f"Histogram {ind['macd_hist']:.1f}"))

    # --- Trend strength: ADX ---
    adx_sig = "neutral"
    if daily and daily["strength"] > 45:
        adx_sig = "bullish" if daily["direction"] == "uptrend" else "bearish" if daily["direction"] == "downtrend" else "neutral"
    factors.append(_factor("ADX Trend Strength", adx_sig, 1.0, f"ADX-derived strength {daily['strength'] if daily else 0:.0f}/100"))

    # --- Volume: OBV ---
    obv_sig = "bullish" if ind["obv_slope"] == "rising" else "bearish"
    factors.append(_factor("OBV Slope", obv_sig, 1.0, f"On-balance volume is {ind['obv_slope']}"))

    if ind["volume_spike"]:
        factors.append(_factor("Volume Spike", "neutral", 0.8, "Latest session volume well above 20-period average -- conviction move, direction TBC by price"))

    # --- Volatility state ---
    if ind["bb_width_pctile"] < 20:
        vol_state = "Compression (low volatility, breakout risk building)"
    elif ind["bb_width_pctile"] > 80:
        vol_state = "Expansion (high volatility, trend may be extended)"
    else:
        vol_state = "Normal"

    # --- Patterns ---
    for p in patterns:
        if p["direction"] != "neutral":
            factors.append(_factor(f"Pattern: {p['name']}", p["direction"], p["confidence"] * 1.2, p["note"]))

    # --- Position vs S/R ---
    # Both lists are nearest-first (index 0 = closest to CMP) as of the levels.py fix --
    # this used to read levels["support"][-1] (the FARTHEST support) here, which was wrong.
    if levels["resistance"] and cmp > levels["resistance"][0] * 0.995:
        factors.append(_factor("Proximity to Resistance", "bearish", 1.2, f"CMP near resistance {levels['resistance'][0]:.0f}"))
    if levels["support"] and cmp < levels["support"][0] * 1.005:
        factors.append(_factor("Proximity to Support", "bullish", 1.2, f"CMP near support {levels['support'][0]:.0f}"))

    # --- Aggregate ---
    score = 0.0
    max_possible = 0.0
    for f in factors:
        max_possible += f["weight"]
        if f["signal"] == "bullish":
            score += f["weight"]
        elif f["signal"] == "bearish":
            score -= f["weight"]

    normalized = (score / max_possible) if max_possible else 0.0  # -1..1
    confidence = round(min(95.0, 50 + abs(normalized) * 50), 1)

    if normalized > 0.15:
        bias = "Bullish"
    elif normalized < -0.15:
        bias = "Bearish"
    else:
        bias = "Neutral"

    momentum_state = "Strong" if abs(ind["macd_hist"]) > ind["atr_14"] * 0.15 and (rsi > 60 or rsi < 40) else "Moderate" if rsi > 55 or rsi < 45 else "Weak/Choppy"

    risk_level = "High" if ind["atr_pct"] > 1.3 or ind["bb_width_pctile"] > 85 else "Medium" if ind["atr_pct"] > 0.8 else "Low"

    return {
        "factors": factors,
        "bias": bias,
        "confidence": confidence,
        "normalized_score": round(normalized, 3),
        "momentum_state": momentum_state,
        "volatility_state": vol_state,
        "risk_level": risk_level,
    }


def scenarios(index_key: str, cmp: float, atr_val: float, levels: dict, bias: str) -> dict:
    cfg = INDEX_REGISTRY[index_key]
    up_target = max(levels["resistance"]) if levels["resistance"] else cmp + atr_val
    down_target = min(levels["support"]) if levels["support"] else cmp - atr_val

    bullish = (
        f"A sustained move above {cmp + atr_val * 0.3:.0f} with volume support opens the path to "
        f"{up_target:.0f}, and extension toward {up_target + atr_val:.0f} if that breaks cleanly."
    )
    bearish = (
        f"A break below {cmp - atr_val * 0.3:.0f} exposes {down_target:.0f} first, with risk of an "
        f"extended slide to {down_target - atr_val:.0f} on a clean breakdown."
    )
    neutral = (
        f"Absent a decisive break of {down_target:.0f}-{up_target:.0f}, expect range-bound, "
        f"two-way price action -- favor selling premium over directional bets."
    )

    invalidation = down_target if bias == "Bullish" else up_target if bias == "Bearish" else cmp

    expected_low = round(cmp - atr_val * 0.8, 1)
    expected_high = round(cmp + atr_val * 0.8, 1)

    return {
        "bullish_scenario": bullish,
        "bearish_scenario": bearish,
        "neutral_scenario": neutral,
        "invalidation_level": round(float(invalidation), 1),
        "expected_range_low": expected_low,
        "expected_range_high": expected_high,
    }
