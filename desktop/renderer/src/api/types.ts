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

export interface SignalQuality {
  key: string;
  n_signals: number;
  n_evaluated: number;
  win_rate: number | null;
  expectancy_r: number | null;
  profit_factor: number | null;
  avg_mfe: number | null;
  avg_mae: number | null;
  e_ratio: number | null;
  payoff_ratio: number | null;
  avg_holding_days: number | null;
  avg_return_pct: number | null;
}

export interface CalibrationBucket {
  label: string;
  lo: number;
  hi: number;
  count: number;
  avg_predicted: number | null;
  actual_win_rate: number | null;
  avg_r: number | null;
}

export interface ConvictionAccuracy {
  pearson_conviction_r: number | null;
  rank_auc: number | null;
  brier_score: number | null;
  monotonic_win_rate: boolean;
}

export interface MoveAccuracy {
  n: number;
  mean_predicted: number | null;
  mean_actual: number | null;
  mean_abs_error: number | null;
  bias: number | null;
}

export interface SignalEvaluation {
  run_id: string | null;
  overall: SignalQuality;
  calibration: CalibrationBucket[];
  conviction_accuracy: ConvictionAccuracy;
  move_accuracy: MoveAccuracy;
  by_source: SignalQuality[];
  by_type: SignalQuality[];
}

export interface EvaluatedSignal {
  signal_id: number;
  symbol: string;
  ts: string;
  signal_type: string;
  direction: string;
  source: string;
  conviction: number | null;
  band: string | null;
  predicted_move_pct: number | null;
  closed: boolean;
  outcome: string;
  r_multiple: number | null;
  return_pct: number | null;
  mfe: number | null;
  mae: number | null;
  holding_days: number | null;
}

export interface SectorHighlight {
  sector: string;
  avg_conviction: number;
  count: number;
}

export interface CommandPerformance {
  n_trades: number;
  expectancy_r: number | null;
  profit_factor: number | null;
  win_rate: number | null;
  net_pnl: number | null;
}

export interface CommandCenter {
  run_id: string | null;
  as_of: string | null;
  regime: Regime | null;
  daily: WatchlistEntry[];
  weekly: WatchlistEntry[];
  monthly: WatchlistEntry[];
  highest_conviction: ConvictionScore | null;
  best_reward_risk: WatchlistEntry | null;
  top_sector: SectorHighlight | null;
  portfolio_heat: number | null;
  equity: number | null;
  daily_pnl: number | null;
  performance: CommandPerformance;
  watchlist_changes: WatchlistComparison | null;
  recent_triggered: Lifecycle[];
}

export interface LifecycleTransition {
  state: string;
  at: string;
  reason: string | null;
}

export interface Lifecycle {
  id: number;
  run_id: string | null;
  symbol: string;
  as_of: string;
  state: string;
  previous_state: string | null;
  state_since: string;
  reason: string | null;
  conviction: number | null;
  sector: string | null;
  history: LifecycleTransition[] | null;
  model_version: string;
}

export interface LifecycleStateCount {
  state: string;
  count: number;
}

export interface LifecycleSummary {
  run_id: string | null;
  total: number;
  states: LifecycleStateCount[];
}

export interface EligibilityFactor {
  name: string;
  label: string;
  status: string; // pass / warn / fail
  score: number;
  weight: number;
  detail: string;
}

export interface OptionsEligibility {
  symbol: string;
  eligible: boolean;
  confidence: number;
  recommendation: string; // "Shares Preferred" | "Leverage Eligible"
  expected_move_pct: number | null;
  factors: EligibilityFactor[];
  summary: string;
}

export interface OptionStructureCandidate {
  structure: string;
  display: string;
  score: number;
  components: Record<string, number>;
}

export interface OptionsAvoidGate {
  name: string;
  passed: boolean;
  detail: string;
}

export interface OptionContract {
  structure: string;
  display: string;
  expiration_days: number;
  strike: number;
  delta: number;
  short_strike: number | null;
  short_delta: number | null;
  risk_level: string; // Low | Medium | High
  contracts: number;
  est_premium_per_contract: number;
  max_loss: number;
  target_profit: number;
  suggested_allocation: number;
  allocation_pct: number;
  reward_to_risk: number | null;
}

export interface OptionsRecommendation {
  symbol: string;
  recommended: boolean;
  structure: string | null;
  contract: OptionContract | null;
  expected_move_pct: number | null;
  candidates: OptionStructureCandidate[];
  gates: OptionsAvoidGate[];
  risk_disclosures: string[];
  summary: string;
  config_hash: string;
}

export interface TradeTarget {
  label: string;
  price: number;
  r_multiple: number;
  gain_pct: number;
  scale_out_pct: number;
}

export interface TradePlan {
  symbol: string;
  entry: number;
  stop: number;
  stop_pct: number;
  risk_per_share: number;
  structural_support: number | null;
  overhead_resistance: number | null;
  targets: TradeTarget[];
  blended_reward_risk: number;
  final_reward_risk: number;
  expected_holding_days_low: number;
  expected_holding_days_high: number;
  suggested_shares: number;
  suggested_position_value: number;
  suggested_portfolio_risk_pct: number;
  suggested_risk_dollars: number;
  risk_summary: string[];
  reward_summary: string[];
  failure_conditions: string[];
  methodology: string[];
}

export interface WatchlistEntry {
  id: number;
  run_id: string | null;
  as_of: string;
  generated_at: string | null;
  horizon: string;
  horizon_label: string;
  rank: number;
  symbol: string;
  conviction: number;
  base_conviction: number;
  band: string | null;
  sector: string | null;
  risk_rating: string;
  horizon_days: number;
  expected_move_pct: number | null;
  expected_risk_pct: number | null;
  reward_risk: number | null;
  model_version: string;
  config_hash: string | null;
}

export interface Watchlist {
  horizon: string;
  label: string;
  as_of: string | null;
  entries: WatchlistEntry[];
}

export interface WatchlistSet {
  run_id: string | null;
  as_of: string | null;
  horizons: Watchlist[];
}

export interface WatchlistMove {
  symbol: string;
  base_rank: number;
  against_rank: number;
  rank_change: number;
  base_conviction: number;
  against_conviction: number;
  conviction_change: number;
}

export interface WatchlistComparison {
  horizon: string;
  base_date: string;
  against_date: string;
  added: WatchlistEntry[];
  removed: WatchlistEntry[];
  moved: WatchlistMove[];
}

export interface DataProviderSettings {
  provider: string;
  keys_present: Record<string, boolean>;
  valid_providers: string[];
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

export interface ConvictionContributor {
  name: string;
  label: string;
  raw: number | null;
  weight: number;
  contribution: number;
  impact: number;
  direction: "positive" | "negative" | string;
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
  contributors: ConvictionContributor[];
  narrative: string | null;
  [k: string]: unknown;
}

export interface AttributionGroup {
  key: string;
  num_trades: number;
  expectancy_r: number | null;
  profit_factor: number | null;
  avg_winner_r: number | null;
  avg_loser_r: number | null;
  win_rate: number | null;
  net_profit: number | null;
}

export interface Attribution {
  run_id: string | null;
  by_sector: AttributionGroup[];
  by_regime: AttributionGroup[];
  by_exit_reason: AttributionGroup[];
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

export interface WatchlistCalibrationBucket {
  label: string;
  lo: number;
  hi: number;
  count: number;
  avg_conviction: number;
  avg_ret_1m: number | null;
  hit_rate: number | null;
}

export interface WatchlistScorecard {
  horizon: string;
  label: string;
  n: number;
  n_complete: number;
  avg_ret_1d: number | null;
  avg_ret_1w: number | null;
  avg_ret_1m: number | null;
  hit_rate_1m: number | null;
  avg_mfe: number | null;
  avg_mae: number | null;
  e_ratio: number | null;
  avg_expected_move: number | null;
  move_capture: number | null;
  expected_move_hit_rate: number | null;
  top_rank_avg_ret_1m: number | null;
  rest_avg_ret_1m: number | null;
  top_minus_rest: number | null;
}

export interface WatchlistPredictionQuality {
  horizon: string;
  label: string;
  n: number;
  ic_conviction: number | null;
  rank_ic: number | null;
  hit_rate_1m: number | null;
  monotonic_calibration: boolean;
  quality_score: number;
  calibration: WatchlistCalibrationBucket[];
}

export interface WatchlistPerformanceReport {
  n_total: number;
  n_complete: number;
  generations: number;
  best_horizon: string | null;
  scorecards: WatchlistScorecard[];
  quality: WatchlistPredictionQuality[];
  generated_at: string;
}

export interface WatchlistPerfEntry {
  as_of: string;
  run_id: string | null;
  horizon: string;
  horizon_label: string;
  symbol: string;
  conviction: number;
  rank: number;
  expected_move_pct: number | null;
  horizon_days: number;
  reference_price: number;
  ret_1d: number | null;
  ret_1w: number | null;
  ret_1m: number | null;
  mfe: number | null;
  mae: number | null;
  bars_tracked: number;
  complete: boolean;
  last_tracked_date: string | null;
}

export interface AuditConvictionBucket {
  label: string;
  lo: number;
  hi: number;
  n: number;
  win_rate: number | null;
  expected_value_r: number | null;
  avg_predicted: number | null;
}

export interface AuditFactorScore {
  name: string;
  ic: number | null;
  p_value: number | null;
  n: number;
  significant: boolean;
  direction: string;
}

export interface AuditCalibration {
  buckets: AuditConvictionBucket[];
  brier_score: number | null;
  monotonic_win_rate: boolean;
  ic: number | null;
  p_value: number | null;
}

export interface AuditArea {
  area: string;
  headline: string;
  metrics: Record<string, number | null>;
  p_value: number | null;
  significant: boolean;
}

export interface SignalAudit {
  n_candidates: number;
  n_with_conviction: number;
  win_rate: number | null;
  expectancy_r: number | null;
  avg_reward_risk: number | null;
  payoff_ratio: number | null;
  max_drawdown_r: number | null;
  conviction_buckets: AuditConvictionBucket[];
  calibration: AuditCalibration;
  factor_scores: AuditFactorScore[];
  strongest_factors: AuditFactorScore[];
  weakest_factors: AuditFactorScore[];
  areas: AuditArea[];
  recommendations: string[];
  caveats: string[];
  config_hash: string;
  generated_at: string;
}
