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
  price: number | null;
  relative_volume: number | null;
  distance_from_ath: number | null;
  sector: string | null;
  as_of: string;
  [k: string]: unknown;
}

export interface Trade {
  id?: number;
  run_id?: string | null;
  symbol: string;
  status: string;
  direction: string;
  entry_price: number | null;
  exit_price: number | null;
  quantity: number | null;
  initial_risk: number | null;
  r_multiple: number | null;
  net_pnl: number | null;
  return_pct: number | null;
  entry_ts: string | null;
  exit_ts: string | null;
  holding_days: number | null;
  mfe: number | null;
  mae: number | null;
  exit_reason: string | null;
  entry_reason: string | null;
  regime_label: string | null;
  sector: string | null;
  [k: string]: unknown;
}

export interface PortfolioSnapshot {
  run_id?: string | null;
  session_date: string;
  equity: number;
  cash?: number;
  num_positions?: number;
  portfolio_heat?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  daily_pnl?: number | null;
  daily_return?: number | null;
  cumulative_return?: number | null;
  drawdown?: number | null;
  [k: string]: unknown;
}

export interface RunDetail {
  run_id: string;
  mode: string;
  as_of: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  equity_start: number | null;
  equity_end: number | null;
  num_opened: number | null;
  num_closed: number | null;
  error: string | null;
}

export interface AuditEvent {
  id: number;
  event_type: string;
  ts: string | null;
  run_id: string | null;
  symbol: string | null;
  entity_type: string | null;
  summary: string | null;
}

export interface Signal {
  id: number;
  run_id: string | null;
  symbol: string;
  ts: string | null;
  signal_type: string | null;
  direction: string | null;
  strength: number | null;
  momentum_score: number | null;
  reference_price: number | null;
  status: string | null;
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

export interface Run {
  run_id: string;
  label: string | null;
}

export interface ConvictionComponent {
  name: string;
  raw: number | null;
  normalized: number;
  weight: number;
  contribution: number;
}

export interface ConvictionScore {
  id: number;
  run_id: string | null;
  symbol: string;
  as_of: string;
  score: number;
  band: string;
  model_version: string;
  config_hash: string | null;
  momentum_score: number | null;
  breakdown: { score?: number; band?: string; components?: ConvictionComponent[] } | null;
  [k: string]: unknown;
}

export interface Opportunity {
  id: number;
  symbol: string;
  as_of: string;
  tier: string;
  score: number;
  new_ath: boolean;
  [k: string]: unknown;
}

export interface RiskBudget {
  conviction_band: string | null;
  opportunity_tier: string | null;
  home_run: boolean;
  base_pct: number;
  requested_pct: number;
  granted_pct: number;
  risk_dollars: number;
  binding_constraint: string | null;
  portfolio_heat_used: number;
  portfolio_heat_after: number;
  reasons: string[];
}

export interface Analogs {
  symbol: string | null;
  regime: string | null;
  sector: string | null;
  sample_size: number;
  expectancy_r: number | null;
  win_rate: number | null;
  avg_winner_r: number | null;
  avg_loser_r: number | null;
  trades: Trade[];
}

export interface CandidateDetail {
  symbol: string;
  scan: ScanResult | null;
  conviction: ConvictionScore | null;
  opportunity: Opportunity | null;
  analogs: Analogs | null;
  risk_budget: RiskBudget | null;
}

// Update / self-update endpoints (src/momentum/api/routes/update.py).
export interface UpdateStatus {
  supported: boolean;
  update_available: boolean;
  current_version: string | null;
  remote_version: string | null;
  branch: string | null;
  behind_by: number;
  reason: string | null;
}

export interface UpdateResult {
  updated: boolean;
  message: string;
  backup_id: string | null;
  from_commit: string | null;
  to_commit: string | null;
}

export interface RollbackResult {
  backup_id: string;
  commit: string;
  version: string | null;
}

// Operator-console background jobs (src/momentum/api/routes/actions.py).
export interface Job {
  id: string;
  kind: string;
  status: "pending" | "running" | "succeeded" | "failed";
  progress: number;
  message: string;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ReplayResult {
  run: Record<string, unknown>;
  open_trades: Record<string, unknown>[];
  closed_trades: Record<string, unknown>[];
  events: Record<string, unknown>[];
}
