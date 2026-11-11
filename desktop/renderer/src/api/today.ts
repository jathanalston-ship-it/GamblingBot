// Types for the simple (primary) screens: GET /today and GET /strategy.

export interface MarketGate {
  uptrend: boolean | null;
  entries_allowed: boolean;
  close: number | null;
  average: number | null;
  period: number;
  symbol: string;
  as_of: string | null;
  headline: string;
  detail: string;
}

export interface TodayData {
  has_scan: boolean;
  run_id: string | null;
  provider?: string;
  universe?: string;
  symbols?: number;
  bars_through?: string | null;
  last_scan_at?: string | null;
  stale: boolean;
}

export interface TodayAccount {
  starting_balance: number;
  equity: number;
  cash: number;
  buying_power: number;
  today_realized_pnl: number;
  unrealized_pnl: number;
  realized_pnl_total: number;
  open_positions: number;
  closed_today: number;
  closed_trades: number;
  win_rate: number | null;
  avg_winner: number | null;
  avg_loser: number | null;
  profit_factor: number | null;
  expectancy_r: number | null;
  largest_winner: number | null;
  largest_loser: number | null;
  max_drawdown: number | null;
  exposure: number;
  exposure_pct: number | null;
  risk_used: number;
  portfolio_heat_pct: number | null;
  max_positions: number;
  slots_free: number;
}

export interface Position {
  trade_uid: string;
  symbol: string;
  sector: string | null;
  shares: number;
  entry_price: number;
  last_price: number;
  value: number;
  pnl: number;
  pnl_pct: number | null;
  r: number | null;
  stop: number;
  exit_level: number | null;
  sell_below: number;
  room_pct: number | null;
  risk_dollars: number;
  days_held: number | null;
  entered_at: string | null;
  mode: string;
  entry_reason: string | null;
}

export interface Signal {
  symbol: string;
  sector: string | null;
  rank: number | null;
  price: number | null;
  momentum_pct: number | null;
  bars_since_breakout: number | null;
  breakout_level: number | null;
  entry: number | null;
  stop: number | null;
  stop_pct: number | null;
  exit_level: number | null;
  shares: number | null;
  position_value: number | null;
  risk_dollars: number | null;
  held: boolean;
  why: string;
}

export interface ActivityItem {
  id: number;
  ts: string | null;
  kind: string;
  symbol: string | null;
  severity: string;
  title: string;
  description: string | null;
}

export interface Evidence {
  run_id: string | null;
  symbols: number | null;
  matches_live_rules: boolean;
  start: string | null;
  end: string | null;
  years: number | null;
  starting_equity: number | null;
  final_equity: number | null;
  cagr: number | null;
  total_return: number | null;
  max_drawdown: number | null;
  benchmark_cagr: number | null;
  benchmark_total_return: number | null;
  benchmark_max_drawdown: number | null;
  num_trades: number;
  win_rate: number;
  expectancy_r: number;
  profit_factor: number;
  avg_winner_r: number;
  avg_loser_r: number;
  largest_winner_r: number;
  avg_holding_days: number;
  exit_reasons: Record<string, number>;
}

export interface Rule {
  title: string;
  text: string;
}

export interface RulesSummary {
  model_version: string;
  config: Record<string, unknown>;
  rules: Rule[];
}

export interface AutopilotBrief {
  enabled: boolean;
  state: string;
  state_label: string;
  activity: string;
  next_action: { label: string; seconds: number | null; at: string | null };
  market_state: string;
  last_error: string | null;
}

export interface Today {
  generated_at: string;
  headline: string;
  market: MarketGate;
  data: TodayData;
  account: TodayAccount;
  positions: Position[];
  signals: Signal[];
  watching: string[];
  autopilot: AutopilotBrief;
  activity: ActivityItem[];
  evidence: Evidence | null;
  rules: RulesSummary;
}

export interface StrategyInfo extends RulesSummary {
  market: MarketGate;
  evidence: Evidence | null;
}
