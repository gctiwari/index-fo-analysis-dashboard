from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel


class LevelSet(BaseModel):
    support: list[float]
    resistance: list[float]
    breakout: Optional[float] = None
    breakdown: Optional[float] = None
    breakout_round_number_confluence: bool = False
    breakdown_round_number_confluence: bool = False


class IndicatorSnapshot(BaseModel):
    rsi_14: float
    macd: float
    macd_signal: float
    macd_hist: float
    stoch_rsi_k: float
    stoch_rsi_d: float
    adx_14: float
    roc_10: float
    atr_14: float
    atr_pct: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_width_pctile: float
    ema_9: float
    ema_20: float
    ema_50: float
    ema_200: float
    sma_20: float
    sma_50: float
    vwap: float
    obv_slope: str
    volume_spike: bool


class DetectedPattern(BaseModel):
    name: str
    category: Literal["candlestick", "chart"]
    direction: Literal["bullish", "bearish", "neutral"]
    timeframe: str
    confidence: float
    note: str


class TrendPicture(BaseModel):
    timeframe: str
    direction: Literal["uptrend", "downtrend", "sideways"]
    structure: str
    strength: float


class ConfluenceFactor(BaseModel):
    factor: str
    signal: Literal["bullish", "bearish", "neutral"]
    weight: float
    detail: str


class MarketOutlook(BaseModel):
    index: str
    display_name: str
    as_of: str
    cmp: float
    change: float
    change_pct: float
    bias: Literal["Bullish", "Bearish", "Neutral"]
    confidence_score: float
    trend_strength: float
    momentum_state: str
    volatility_state: str
    risk_level: Literal["Low", "Medium", "High"]
    levels: LevelSet
    expected_range_low: float
    expected_range_high: float
    bullish_scenario: str
    bearish_scenario: str
    neutral_scenario: str
    invalidation_level: float
    probability_gap_up: float
    probability_gap_down: float
    expected_opening: str
    key_indicators: IndicatorSnapshot
    trends_mtf: list[TrendPicture]
    patterns: list[DetectedPattern]
    confluence_factors: list[ConfluenceFactor]
    risk_warnings: list[str]
    executive_summary: str


class TradeIdea(BaseModel):
    index: str
    direction: Literal["Bullish (Buy Call)", "Bearish (Buy Put)"]
    option_type: Literal["CALL", "PUT"]
    strike: float
    expiry: str
    estimated_premium: float
    cmp: float
    entry_type: Literal["Immediate", "Wait", "Conditional"]
    entry_trigger: str
    reasoning: str
    technical_factors: list[str]
    pattern_support: list[str]
    momentum_support: str
    risk_level: Literal["Low", "Medium", "High"]
    probability_score: float
    target_1: float
    target_2: float
    target_3: float
    hard_stop_loss: float
    risk_reward_ratio: float
    expected_holding_period: str
    invalidation_condition: str
    max_acceptable_loss_per_lot: float
    lot_size: int
    recommended_lots: str
    capital_required_approx: float
    trade_notes: str
    alternative_trade: str


class TradesResponse(BaseModel):
    index: str
    as_of: str
    has_trade: bool
    reason_if_none: Optional[str] = None
    ideas: list[TradeIdea]
