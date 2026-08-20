export interface IndexMeta {
  key: string;
  name: string;
  live: boolean;
}

export interface LevelSet {
  support: number[];
  resistance: number[];
  breakout: number | null;
  breakdown: number | null;
  breakout_round_number_confluence: boolean;
  breakdown_round_number_confluence: boolean;
}

export interface IndicatorSnapshot {
  rsi_14: number;
  macd: number;
  macd_signal: number;
  macd_hist: number;
  stoch_rsi_k: number;
  stoch_rsi_d: number;
  adx_14: number;
  roc_10: number;
  atr_14: number;
  atr_pct: number;
  bb_upper: number;
  bb_middle: number;
  bb_lower: number;
  bb_width_pctile: number;
  ema_9: number;
  ema_20: number;
  ema_50: number;
  ema_200: number;
  sma_20: number;
  sma_50: number;
  vwap: number;
  obv_slope: string;
  volume_spike: boolean;
}

export interface DetectedPattern {
  name: string;
  category: "candlestick" | "chart";
  direction: "bullish" | "bearish" | "neutral";
  timeframe: string;
  confidence: number;
  note: string;
}

export interface TrendPicture {
  timeframe: string;
  direction: "uptrend" | "downtrend" | "sideways";
  structure: string;
  strength: number;
}

export interface ConfluenceFactor {
  factor: string;
  signal: "bullish" | "bearish" | "neutral";
  weight: number;
  detail: string;
}

export interface MarketOutlook {
  index: string;
  display_name: string;
  as_of: string;
  cmp: number;
  change: number;
  change_pct: number;
  bias: "Bullish" | "Bearish" | "Neutral";
  confidence_score: number;
  trend_strength: number;
  momentum_state: string;
  volatility_state: string;
  risk_level: "Low" | "Medium" | "High";
  levels: LevelSet;
  expected_range_low: number;
  expected_range_high: number;
  bullish_scenario: string;
  bearish_scenario: string;
  neutral_scenario: string;
  invalidation_level: number;
  probability_gap_up: number;
  probability_gap_down: number;
  expected_opening: string;
  key_indicators: IndicatorSnapshot;
  trends_mtf: TrendPicture[];
  patterns: DetectedPattern[];
  confluence_factors: ConfluenceFactor[];
  risk_warnings: string[];
  executive_summary: string;
}
