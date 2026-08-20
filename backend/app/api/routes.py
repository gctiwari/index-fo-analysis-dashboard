from __future__ import annotations
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.config import INDEX_REGISTRY, ACTIVE_INDICES
from app.data.fetcher import get_ohlcv, get_macro_snapshot, DataUnavailableError
from app.analysis.indicators import build_indicator_snapshot
from app.analysis.patterns import detect_candlesticks, detect_chart_patterns
from app.analysis.levels import trend_structure, support_resistance, gap_analysis
from app.analysis.confluence import build_confluence, scenarios

router = APIRouter()

MTF_TIMEFRAMES = ["1wk", "1d", "4h", "1h", "15m"]


@router.get("/indices")
def list_indices():
    return [
        {"key": k, "name": v.display_name, "live": bool(v.yf_ticker)}
        for k, v in INDEX_REGISTRY.items()
    ]


@router.get("/macro")
def macro_snapshot():
    return get_macro_snapshot()


def _analyze_index(index_key: str):
    if index_key not in INDEX_REGISTRY:
        raise HTTPException(404, f"Unknown index '{index_key}'")
    if index_key not in ACTIVE_INDICES:
        raise HTTPException(409, f"No live data source configured for '{index_key}' yet.")

    try:
        daily_df = get_ohlcv(index_key, "1d")
    except DataUnavailableError as exc:
        raise HTTPException(502, str(exc)) from exc

    cmp = float(daily_df["close"].iloc[-1])
    prev_close = float(daily_df["close"].iloc[-2])
    change = cmp - prev_close
    change_pct = change / prev_close * 100

    ind = build_indicator_snapshot(daily_df)
    candle_patterns = detect_candlesticks(daily_df, "1d")
    chart_patterns = detect_chart_patterns(daily_df, "1d")
    all_patterns = candle_patterns + chart_patterns
    levels = support_resistance(daily_df)
    gap = gap_analysis(daily_df)

    trends = []
    for tf in MTF_TIMEFRAMES:
        try:
            tf_df = daily_df if tf == "1d" else get_ohlcv(index_key, tf)
            trends.append(trend_structure(tf_df, tf))
        except DataUnavailableError:
            continue

    confluence = build_confluence(ind, trends, all_patterns, levels, cmp)
    scen = scenarios(index_key, cmp, ind["atr_14"], levels, confluence["bias"])

    # Gap probability heuristic: based on recent gap frequency + current bias/momentum
    recent_gaps = daily_df["open"] - daily_df["close"].shift(1)
    recent_gap_pct = (recent_gaps / daily_df["close"].shift(1) * 100).dropna().tail(30)
    base_gap_up_rate = float((recent_gap_pct > 0.15).mean()) * 100
    base_gap_down_rate = float((recent_gap_pct < -0.15).mean()) * 100
    bias_tilt = 8 if confluence["bias"] == "Bullish" else -8 if confluence["bias"] == "Bearish" else 0
    prob_gap_up = round(max(5, min(85, base_gap_up_rate + bias_tilt)), 1)
    prob_gap_down = round(max(5, min(85, base_gap_down_rate - bias_tilt)), 1)

    expected_opening = (
        f"Gap-up open likely near {cmp + ind['atr_14'] * 0.2:.0f}" if confluence["bias"] == "Bullish" and prob_gap_up > 40
        else f"Gap-down open possible near {cmp - ind['atr_14'] * 0.2:.0f}" if confluence["bias"] == "Bearish" and prob_gap_down > 40
        else "Flat-to-mildly directional open expected, in line with prior close"
    )

    risk_warnings = []
    if ind["bb_width_pctile"] < 15:
        risk_warnings.append("Volatility is compressed to multi-session lows -- a sharp breakout move is possible in either direction.")
    if ind["atr_pct"] > 1.4:
        risk_warnings.append("ATR is elevated -- widen stops and reduce position size versus normal conditions.")
    if gap:
        risk_warnings.append(f"Latest session opened with a {gap['type'].replace('_', ' ')} of {gap['gap_pct']}% -- gap-fill risk in play.")
    if confluence["confidence"] < 60:
        risk_warnings.append("Confluence is only moderate -- this is a lower-conviction read; avoid oversized positioning.")
    daily_trend = next((t for t in trends if t["timeframe"] == "1d"), None)
    weekly_trend = next((t for t in trends if t["timeframe"] == "1wk"), None)
    if daily_trend and weekly_trend and daily_trend["direction"] != weekly_trend["direction"]:
        risk_warnings.append("Daily and weekly trend structures disagree -- treat intraday signals as tactical, not positional.")
    if not risk_warnings:
        risk_warnings.append("No acute structural risk flagged; standard position-sizing discipline still applies.")

    top_factors_text = "; ".join(f["detail"] for f in confluence["factors"] if f["signal"] != "neutral")[:0]  # placeholder unused
    bullish_n = sum(1 for f in confluence["factors"] if f["signal"] == "bullish")
    bearish_n = sum(1 for f in confluence["factors"] if f["signal"] == "bearish")
    exec_summary = (
        f"{INDEX_REGISTRY[index_key].display_name} is at {cmp:,.0f} ({change_pct:+.2f}% vs prior close), "
        f"with a {confluence['bias'].upper()} bias at {confluence['confidence']:.0f}% confidence "
        f"({bullish_n} bullish vs {bearish_n} bearish factors). "
        f"{daily_trend['structure'] if daily_trend else 'Trend structure unclear'} on the daily chart, "
        f"{confluence['volatility_state'].lower()}, momentum reads {confluence['momentum_state'].lower()}. "
        f"Key levels to track: support {levels['support'][0] if levels['support'] else 'n/a'}, "
        f"resistance {levels['resistance'][0] if levels['resistance'] else 'n/a'}. "
        + (scen['bullish_scenario'] if confluence['bias'] == 'Bullish' else scen['bearish_scenario'] if confluence['bias'] == 'Bearish' else scen['neutral_scenario'])
    )

    outlook = {
        "index": index_key,
        "display_name": INDEX_REGISTRY[index_key].display_name,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "cmp": round(cmp, 1),
        "change": round(change, 1),
        "change_pct": round(change_pct, 2),
        "bias": confluence["bias"],
        "confidence_score": confluence["confidence"],
        "trend_strength": daily_trend["strength"] if daily_trend else 0,
        "momentum_state": confluence["momentum_state"],
        "volatility_state": confluence["volatility_state"],
        "risk_level": confluence["risk_level"],
        "levels": levels,
        **scen,
        "probability_gap_up": prob_gap_up,
        "probability_gap_down": prob_gap_down,
        "expected_opening": expected_opening,
        "key_indicators": ind,
        "trends_mtf": trends,
        "patterns": all_patterns,
        "confluence_factors": confluence["factors"],
        "risk_warnings": risk_warnings,
        "executive_summary": exec_summary,
    }
    return outlook, ind, all_patterns, levels, confluence, cmp


@router.get("/outlook/{index_key}")
def get_outlook(index_key: str):
    outlook, *_ = _analyze_index(index_key.upper())
    return outlook

# Note: there is deliberately no live "recompute a trade idea on every request"
# endpoint here anymore. A trade recommendation is a decision that should be
# made ONCE and then tracked against -- that's what /api/tracking/{index}/today
# does (see tracking_routes.py): it generates one idea per day, locks it in,
# and reports live status (distance to trigger, progress to target) against
# that fixed plan rather than silently regenerating a new one on every refresh.
