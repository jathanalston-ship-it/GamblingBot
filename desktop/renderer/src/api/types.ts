// Response shapes mirroring the FastAPI read API (src/momentum/api/schemas.py).
// Records carry an index signature so they drop straight into the generic table.

export interface Regime {
  as_of: string;
  regime: string;
  [k: string]: unknown;
}

export interface ScanResult {
  symbol: string;
  momentum_score: number;
  rank: number;
  passed: boolean;
  relative_volume: number | null;
  distance_from_ath: number | null;
  sector: string | null;
  as_of: string;
  [k: string]: unknown;
}

export interface Trade {
  symbol: string;
  status: string;
  direction: string;
  entry_price: number | null;
  exit_price: number | null;
  r_multiple: number | null;
  net_pnl: number | null;
  entry_ts: string | null;
  exit_ts: string | null;
  sector: string | null;
  [k: string]: unknown;
}

export interface PortfolioSnapshot {
  session_date: string;
  equity: number;
  [k: string]: unknown;
}

export interface RiskMetric {
  as_of: string;
  scope: string;
  window: string | null;
  [k: string]: unknown;
}

export interface Optimization {
  study_name: string;
  objective_value: number;
  [k: string]: unknown;
}

export interface Performance {
  run_id: string | null;
  n_trades: number;
  trade_stats: Record<string, number | null>;
  performance: Record<string, number> | null;
}

export interface Dashboard {
  latest_regime: Regime | null;
  latest_snapshot: PortfolioSnapshot | null;
  top_scans: ScanResult[];
  recent_trades: Trade[];
  open_trades: number;
  performance: Performance;
}

export interface ConfigFile {
  name: string;
  content: string;
  parsed: Record<string, unknown> | null;
}
