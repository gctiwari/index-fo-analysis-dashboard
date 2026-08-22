export interface PaperTradeRecord {
  id: number;
  index: string;
  role?: string | null;
  trade_date: string;
  entry_index_level: number;
  entry_premium: number;
  entry_time: string | null;
  exit_index_level: number | null;
  exit_premium: number | null;
  exit_time: string | null;
  targets_hit: string[];
  stop_hit: boolean;
  status: "OPEN" | "CLOSED";
  outcome: string | null;
  pnl_rupees: number | null;
  pnl_pct: number | null;
}

export interface LiveStatus {
  available: boolean;
  current_price: number | null;
  distance_to_trigger?: number;
  trigger_reached?: boolean;
  current_premium?: number;
  unrealized_pnl_pct?: number;
  progress_to_target_1_pct?: number;
}

export interface RecommendationDiagnostics {
  monitor_tick_count: number;
  unique_candles_checked: number;
  last_price_checked: number | null;
  last_price_checked_at: string | null;
  last_check_source: string | null;
  last_completed_candle_timestamp: string | null;
  last_completed_candle_close: number | null;
  mfe_index_level: number | null;
  trigger_reached_at: string | null;
}

export interface RecommendationRecord {
  id: number;
  index: string;
  role: "PRIMARY" | "BREAKOUT_UP" | "BREAKOUT_DOWN";
  trade_date: string;
  generated_at: string | null;
  status: "PENDING" | "EXECUTED" | "NOT_EXECUTED" | "NO_SIGNAL" | "INVALIDATED";
  not_executed_reason: string | null;
  no_signal_reason: string | null;
  invalidated_reason: string | null;
  invalidated_at: string | null;
  direction: string | null;
  option_type: "CALL" | "PUT" | null;
  strike: number | null;
  expiry: string | null;
  lot_size: number | null;
  cmp_at_generation: number | null;
  premium_at_generation: number | null;
  entry_type: string | null;
  entry_trigger_desc: string | null;
  entry_trigger_index_level: number | null;
  stop_index_level: number | null;
  target_premium_1: number | null;
  target_premium_2: number | null;
  target_premium_3: number | null;
  stop_premium: number | null;
  confidence_score: number | null;
  reasoning: string | null;
  raw: Record<string, unknown> | null;
  paper_trade: PaperTradeRecord | null;
  live?: LiveStatus;
  diagnostics: RecommendationDiagnostics;
}

export interface PerformanceStats {
  index: string;
  total_trading_days_tracked: number;
  signal_days: number;
  no_signal_days: number;
  executed_count: number;
  not_executed_count: number;
  pct_executed: number;
  open_trades_count: number;
  closed_trades_count: number;
  win_rate_pct: number;
  avg_return_pct_per_trade: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  best_trade_pct: number;
  worst_trade_pct: number;
  total_pnl_rupees_per_lot: number;
}

export interface EquityCurvePoint {
  seq: number;
  trade_date: string | null;
  exit_time: string | null;
  index: string | null;
  trade_pnl_rupees: number | null;
  trade_pnl_pct: number | null;
  cumulative_pnl_rupees: number;
  cumulative_pnl_pct: number;
  outcome: string;
}

export interface PerformanceResponse {
  overall: PerformanceStats;
  per_index: PerformanceStats[];
}
