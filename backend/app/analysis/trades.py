"""
Rule-based options trade-idea generator.

IMPORTANT: without a live NSE option-chain / broker feed, real bid-ask
premiums aren't available. Premiums here are estimated with Black-Scholes
using ATR-derived realized volatility as a proxy for IV -- clearly labeled
as an ESTIMATE in the output, never presented as a live quote. Swap
`estimate_premium` for a real option-chain lookup once a data vendor
(e.g. Kite Connect, TrueData, NSE feed) is connected.
"""
from __future__ import annotations
import math
from datetime import date, timedelta
from statistics import NormalDist

from app.config import INDEX_REGISTRY, RISK_FREE_RATE

_N = NormalDist()


def _next_weekly_expiry(today: date | None = None) -> date:
    today = today or date.today()
    days_ahead = (3 - today.weekday()) % 7  # Thursday = 3
    days_ahead = days_ahead or 7
    return today + timedelta(days=days_ahead)


def estimate_premium(spot: float, strike: float, days_to_expiry: int, atr_pct: float, option_type: str) -> float:
    t = max(days_to_expiry, 1) / 365
    sigma = max(atr_pct / 100 * math.sqrt(252), 0.08)  # annualize daily ATR% as a vol proxy, floor at 8%
    d1 = (math.log(spot / strike) + (RISK_FREE_RATE + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if option_type == "CALL":
        price = spot * _N.cdf(d1) - strike * math.exp(-RISK_FREE_RATE * t) * _N.cdf(d2)
    else:
        price = strike * math.exp(-RISK_FREE_RATE * t) * _N.cdf(-d2) - spot * _N.cdf(-d1)
    return max(round(price, 1), 0.5)


def nearest_strike(cmp: float, interval: int, otm_steps: int = 0, direction: str = "CALL") -> float:
    atm = round(cmp / interval) * interval
    if direction == "CALL":
        return atm + interval * otm_steps
    return atm - interval * otm_steps


def generate_trade_idea(index_key: str, cmp: float, confluence: dict, ind: dict, patterns: list[dict], levels: dict) -> dict | None:
    """Returns None if confluence doesn't clear the high-conviction bar."""
    cfg = INDEX_REGISTRY[index_key]
    bias = confluence["bias"]
    confidence = confluence["confidence"]

    # Require real confluence: at least moderate confidence AND at least 4 agreeing factors
    agreeing = [f for f in confluence["factors"] if f["signal"] == ("bullish" if bias == "Bullish" else "bearish")]
    if bias == "Neutral" or confidence < 62 or len(agreeing) < 4:
        return None

    option_type = "CALL" if bias == "Bullish" else "PUT"
    strike = nearest_strike(cmp, cfg.strike_interval, otm_steps=1, direction=option_type)
    expiry = _next_weekly_expiry()
    dte = max((expiry - date.today()).days, 1)
    premium = estimate_premium(cmp, strike, dte, ind["atr_pct"], option_type)

    atr_val = ind["atr_14"]
    if option_type == "CALL":
        t1, t2, t3 = cmp + atr_val * 0.8, cmp + atr_val * 1.5, cmp + atr_val * 2.3
        stop_index_level = cmp - atr_val * 0.9
    else:
        t1, t2, t3 = cmp - atr_val * 0.8, cmp - atr_val * 1.5, cmp - atr_val * 2.3
        stop_index_level = cmp + atr_val * 0.9

    # Translate index-level stop into a rough premium-based stop (delta-scaled approx)
    moneyness = abs(cmp - strike) / cmp
    approx_delta = max(0.25, 0.5 - moneyness * 3)
    premium_stop = max(round(premium * (1 - approx_delta), 1), premium * 0.4)
    risk_per_lot = round((premium - premium_stop) * cfg.lot_size, 0)
    reward_per_lot = round((estimate_premium(t2, strike, dte, ind["atr_pct"], option_type) - premium) * cfg.lot_size, 0)
    rr = round(reward_per_lot / risk_per_lot, 2) if risk_per_lot > 0 else 0.0

    tech_factors = [f["detail"] for f in agreeing[:5]]
    pattern_names = [p["name"] for p in patterns if p["direction"] == ("bullish" if bias == "Bullish" else "bearish")]

    entry_type = "Immediate" if confidence >= 75 else "Conditional"
    entry_trigger_index_level = (
        cmp + atr_val * 0.25 if option_type == "CALL" else cmp - atr_val * 0.25
    ) if entry_type == "Conditional" else cmp
    trigger = (
        f"Enter on a 15-min close beyond {entry_trigger_index_level:.0f}" if option_type == "CALL" and entry_type == "Conditional"
        else f"Enter on a 15-min close below {entry_trigger_index_level:.0f}" if entry_type == "Conditional"
        else "Current price action already confirms the setup; enter at CMP."
    )

    reasoning = (
        f"{len(agreeing)} independent factors align {bias.lower()}: "
        + "; ".join(tech_factors[:3]) + "."
    )

    alt_strike = nearest_strike(cmp, cfg.strike_interval, otm_steps=2, direction=option_type)
    alt_premium = estimate_premium(cmp, alt_strike, dte, ind["atr_pct"], option_type)
    alternative = (
        f"More aggressive (higher risk-reward, lower probability): {alt_strike:.0f} {option_type} "
        f"~₹{alt_premium} premium."
    )

    capital_required = round(premium * cfg.lot_size * 2, 0)  # approx for 2 lots

    return {
        "index": index_key,
        "direction": "Bullish (Buy Call)" if option_type == "CALL" else "Bearish (Buy Put)",
        "option_type": option_type,
        "strike": strike,
        "expiry": expiry.isoformat(),
        "estimated_premium": premium,
        "cmp": round(cmp, 1),
        "entry_type": entry_type,
        "entry_trigger": trigger,
        "reasoning": reasoning,
        "technical_factors": tech_factors,
        "pattern_support": pattern_names or ["No fresh candlestick/chart pattern -- trade relies on trend + momentum confluence"],
        "momentum_support": confluence["momentum_state"],
        "risk_level": confluence["risk_level"],
        "probability_score": confidence,
        "target_1": round(estimate_premium(t1, strike, dte, ind["atr_pct"], option_type), 1),
        "target_2": round(estimate_premium(t2, strike, dte, ind["atr_pct"], option_type), 1),
        "target_3": round(estimate_premium(t3, strike, dte, ind["atr_pct"], option_type), 1),
        "hard_stop_loss": premium_stop,
        "risk_reward_ratio": rr,
        "expected_holding_period": "Intraday to 2 trading sessions" if dte <= 3 else "2-4 trading sessions into expiry",
        "invalidation_condition": f"Index-level invalidation near {stop_index_level:.0f}; exit the option regardless of premium if this level is breached on a closing basis.",
        "max_acceptable_loss_per_lot": abs(risk_per_lot),
        "lot_size": cfg.lot_size,
        "recommended_lots": "1-2 lots (cap risk to a small % of capital; do not average a losing option position)",
        "capital_required_approx": capital_required,
        "trade_notes": (
            "Premium figures are model-estimated (Black-Scholes on ATR-proxy volatility), not a live option-chain quote. "
            "Verify actual bid-ask, OI and IV on your broker terminal before entry."
        ),
        "alternative_trade": alternative,
        # Internal fields (not part of the public TradeIdea schema) used by the tracker
        # to monitor entry/target/stop against the live index level.
        "_entry_trigger_index_level": round(float(entry_trigger_index_level), 1),
        "_target_index_1": round(float(t1), 1),
        "_target_index_2": round(float(t2), 1),
        "_target_index_3": round(float(t3), 1),
        "_stop_index_level": round(float(stop_index_level), 1),
        "_atr_pct": ind["atr_pct"],
    }


def generate_breakout_bracket(index_key: str, cmp: float, ind: dict, levels: dict, confluence: dict) -> list[dict]:
    """
    Two independent, level-triggered watches -- NOT confluence-gated, unlike
    generate_trade_idea(). The premise here is deliberately different: "we
    don't need to predict direction, we just react if price actually breaks
    a real support/resistance level with conviction."

    - If price closes above resistance -> buy a call at that level
    - If price closes below support -> buy a put at that level

    `levels["breakout"]`/`levels["breakdown"]` (from levels.py) are already
    None unless the nearest resistance/support sits within a realistic,
    ATR-scaled band of CMP -- so if the market structure genuinely has no
    nearby level, this function correctly returns fewer than 2 ideas rather
    than inventing a distant one. That's intentional: a missing leg should
    surface as WAIT / NO TRADE in the UI, not a forced trade.

    These are two separate conditional orders, not a strict OCO pair (both
    could in theory trigger on an extreme whipsaw day, though that's rare).
    Because there's no confluence gate, treat these as lower average
    conviction than the Primary pick by default -- risk/probability below
    are adjusted using the SAME trend/volatility data the confluence engine
    already computed (not a new fabricated indicator): a breakout aligned
    with the prevailing daily trend, or occurring out of a volatility
    squeeze, is a genuinely more standard, higher-quality setup than one
    fighting the trend in a choppy tape -- that's ordinary technical
    analysis, just applied consistently instead of a flat constant.

    IMPORTANT (repeating the standing caveat because it matters most here):
    these are model estimates built on ATR-derived volatility, not live
    option-chain quotes, and breakouts fail often enough in practice that
    a hard stop-loss is included on every leg below -- there is no version
    of this, or any other analysis tool, that eliminates the risk of loss.
    """
    cfg = INDEX_REGISTRY[index_key]
    expiry = _next_weekly_expiry()
    dte = max((expiry - date.today()).days, 1)

    ideas: list[dict] = []

    resistance = levels.get("breakout")
    if resistance:
        round_confluence = bool(levels.get("breakout_round_number_confluence"))
        note = f"Watching resistance at {resistance:.0f} ({abs(resistance - cmp) / max(ind['atr_14'], 0.01):.1f}x ATR away). "
        note += "If the index closes above it, that's often the start of a fresh leg higher as short-covering and breakout buying kick in."
        if round_confluence:
            note += " This level also sits on a round-number order-flow cluster, which typically reinforces it."
        ideas.append(_build_breakout_leg(
            index_key, cfg, "CALL", trigger_level=resistance, cmp=cmp, ind=ind, expiry=expiry, dte=dte,
            confluence=confluence, round_confluence=round_confluence, note=note,
        ))

    support = levels.get("breakdown")
    if support:
        round_confluence = bool(levels.get("breakdown_round_number_confluence"))
        note = f"Watching support at {support:.0f} ({abs(cmp - support) / max(ind['atr_14'], 0.01):.1f}x ATR away). "
        note += "If the index closes below it, that often accelerates into stop-loss selling and fresh shorts."
        if round_confluence:
            note += " This level also sits on a round-number order-flow cluster, which typically reinforces it."
        ideas.append(_build_breakout_leg(
            index_key, cfg, "PUT", trigger_level=support, cmp=cmp, ind=ind, expiry=expiry, dte=dte,
            confluence=confluence, round_confluence=round_confluence, note=note,
        ))

    return ideas


def _build_breakout_leg(index_key: str, cfg, option_type: str, trigger_level: float, cmp: float, ind: dict, expiry, dte: int, confluence: dict, round_confluence: bool, note: str) -> dict:
    atr_val = ind["atr_14"]
    strike = nearest_strike(trigger_level, cfg.strike_interval, otm_steps=0, direction=option_type)
    premium_at_trigger = estimate_premium(trigger_level, strike, dte, ind["atr_pct"], option_type)

    if option_type == "CALL":
        t1, t2, t3 = trigger_level + atr_val * 0.8, trigger_level + atr_val * 1.5, trigger_level + atr_val * 2.3
        stop_index_level = trigger_level - atr_val * 0.6  # a failed breakout that falls back through the level
        direction_label = "Bullish (Buy Call) — IF price breaks ABOVE this level"
        aligned_with_bias = confluence["bias"] == "Bullish"
    else:
        t1, t2, t3 = trigger_level - atr_val * 0.8, trigger_level - atr_val * 1.5, trigger_level - atr_val * 2.3
        stop_index_level = trigger_level + atr_val * 0.6  # a failed breakdown that recovers back through the level
        direction_label = "Bearish (Buy Put) — IF price breaks BELOW this level"
        aligned_with_bias = confluence["bias"] == "Bearish"

    # Data-driven (not fabricated) risk/probability adjustment: reuse the confluence
    # engine's own trend bias and volatility read instead of a flat constant.
    is_compressed = "Compression" in confluence.get("volatility_state", "")
    probability_score = 40.0
    if aligned_with_bias:
        probability_score += 15.0  # breakout direction agrees with the prevailing daily trend
    if is_compressed:
        probability_score += 8.0  # breakouts out of a volatility squeeze tend to follow through more often
    if round_confluence:
        probability_score += 5.0  # a round-number order-flow cluster reinforcing a real technical level
    probability_score = min(probability_score, 58.0)  # stays below the Primary pick's 62% high-conviction bar by design
    risk_level = "Medium" if aligned_with_bias else "High"

    reasoning_extra = (
        " This direction matches the day's overall trend bias, which improves the odds of genuine follow-through rather than a fakeout."
        if aligned_with_bias else
        " This runs counter to the day's overall trend bias -- breakouts against the prevailing trend fail more often, so this leg is priced as lower-probability and sized down."
    )

    premium_stop = estimate_premium(stop_index_level, strike, dte, ind["atr_pct"], option_type)
    risk_per_lot = round((premium_at_trigger - premium_stop) * cfg.lot_size, 0)
    reward_per_lot = round((estimate_premium(t2, strike, dte, ind["atr_pct"], option_type) - premium_at_trigger) * cfg.lot_size, 0)
    rr = round(reward_per_lot / risk_per_lot, 2) if risk_per_lot > 0 else 0.0
    capital_required = round(premium_at_trigger * cfg.lot_size * 2, 0)

    return {
        "index": index_key,
        "direction": direction_label,
        "option_type": option_type,
        "strike": strike,
        "expiry": expiry.isoformat(),
        "estimated_premium": premium_at_trigger,
        "cmp": round(cmp, 1),
        "entry_type": "Conditional",
        "entry_trigger": f"Enter only if the index closes {'above' if option_type == 'CALL' else 'below'} {trigger_level:.0f} — do not enter before that.",
        "reasoning": note + " No confluence gate is applied to this leg (unlike the Primary pick) — it's a reactive, level-triggered play, sized and stopped accordingly." + reasoning_extra,
        "technical_factors": [f"Level-triggered breakout at {trigger_level:.0f} (pivot/swing/round-number confluence, nearest qualifying level within a realistic ATR-scaled distance)"],
        "pattern_support": ["Not confluence-gated — this leg relies purely on the level breaking, not on multi-factor agreement"],
        "momentum_support": "To be confirmed at trigger (unknown until price actually reaches the level)",
        "risk_level": risk_level,
        "probability_score": probability_score,
        "target_1": round(estimate_premium(t1, strike, dte, ind["atr_pct"], option_type), 1),
        "target_2": round(estimate_premium(t2, strike, dte, ind["atr_pct"], option_type), 1),
        "target_3": round(estimate_premium(t3, strike, dte, ind["atr_pct"], option_type), 1),
        "hard_stop_loss": premium_stop,
        "risk_reward_ratio": rr,
        "expected_holding_period": "Intraday to 2 trading sessions" if dte <= 3 else "2-4 trading sessions into expiry",
        "invalidation_condition": f"If price closes back through {trigger_level:.0f} after triggering, treat it as a failed breakout and exit at the stop regardless of premium.",
        "max_acceptable_loss_per_lot": abs(risk_per_lot),
        "lot_size": cfg.lot_size,
        "recommended_lots": "1 lot only — this leg has no confluence backing, size it smaller than the Primary pick",
        "capital_required_approx": capital_required,
        "trade_notes": (
            "This is a reactive breakout/breakdown watch, not a confluence-backed call. Premiums are model estimates "
            "(Black-Scholes on ATR-proxy volatility) for if/when the trigger level is reached — not a live quote. "
            "Breakouts fail often enough that the stop-loss above is not optional. No analysis tool, this one "
            "included, can guarantee a trade won't lose money — verify everything on your broker terminal and "
            "size positions so a stop-out is a cost you can absorb without issue."
        ),
        "alternative_trade": "This is already the higher-risk, reactive alternative to the Primary pick — there isn't a further variant offered for this leg.",
        "_entry_trigger_index_level": round(float(trigger_level), 1),
        "_target_index_1": round(float(t1), 1),
        "_target_index_2": round(float(t2), 1),
        "_target_index_3": round(float(t3), 1),
        "_stop_index_level": round(float(stop_index_level), 1),
        "_atr_pct": ind["atr_pct"],
    }
