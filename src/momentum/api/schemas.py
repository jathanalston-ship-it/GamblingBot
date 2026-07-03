"""Pydantic response models for the read API.

These are the API contract, intentionally decoupled from the SQLAlchemy ORM
models. ``from_attributes`` lets FastAPI serialize ORM rows directly against
them. Read-only — the API never accepts write payloads.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthOut(BaseModel):
    status: str
    service: str
    version: str


class UpdateStatusOut(BaseModel):
    """Whether an update is supported here and, if so, whether one is available."""

    supported: bool
    update_available: bool
    current_version: str | None = None
    remote_version: str | None = None
    branch: str | None = None
    behind_by: int = 0
    reason: str | None = None


class UpdateResultOut(BaseModel):
    updated: bool
    message: str
    backup_id: str | None = None
    from_commit: str | None = None
    to_commit: str | None = None


class RollbackResultOut(BaseModel):
    backup_id: str
    commit: str
    version: str | None = None


class JobOut(BaseModel):
    """A background operator-console job: status, progress and result/error."""

    id: str
    kind: str
    status: str  # pending | running | succeeded | failed
    progress: float
    message: str
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    finished_at: str | None = None


class ReplayOut(BaseModel):
    run: dict[str, Any]
    open_trades: list[dict[str, Any]]
    closed_trades: list[dict[str, Any]]
    events: list[dict[str, Any]]


class SignalOut(_ORMModel):
    id: int
    run_id: str | None
    source: str
    strategy: str
    symbol: str
    ts: dt.datetime
    session_date: dt.date
    signal_type: str
    direction: str
    status: str
    strength: float | None
    momentum_score: float | None
    breakout_level: float | None
    reference_price: float | None
    atr: float | None
    regime_id: int | None


class TradeOut(_ORMModel):
    id: int
    run_id: str | None
    symbol: str
    direction: str
    status: str
    entry_ts: dt.datetime
    exit_ts: dt.datetime | None
    entry_price: float
    exit_price: float | None
    quantity: int
    initial_stop: float | None
    initial_risk: float | None
    r_multiple: float | None
    gross_pnl: float | None
    net_pnl: float | None
    fees: float
    return_pct: float | None
    mae: float | None
    mfe: float | None
    holding_days: int | None
    exit_reason: str | None
    sector: str | None
    regime_label: str | None
    entry_reason: str | None


class RegimeOut(_ORMModel):
    id: int
    as_of: dt.date
    benchmark_symbol: str
    model_version: str
    regime: str
    trend_state: str
    volatility_state: str
    score: float
    confidence: float | None
    ma_fast: float | None
    ma_slow: float | None
    adx: float | None
    realized_vol: float | None
    breadth: float | None


class PortfolioSnapshotOut(_ORMModel):
    id: int
    run_id: str | None
    as_of: dt.datetime
    session_date: dt.date
    equity: float
    cash: float
    positions_value: float
    num_positions: int
    gross_exposure: float
    net_exposure: float
    leverage: float
    portfolio_heat: float
    realized_pnl: float
    unrealized_pnl: float
    daily_pnl: float | None
    daily_return: float | None
    cumulative_return: float | None
    drawdown: float | None


class RiskMetricOut(_ORMModel):
    id: int
    run_id: str | None
    as_of: dt.datetime
    session_date: dt.date
    scope: str
    window: str
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    max_drawdown: float | None
    volatility_annual: float | None
    win_rate: float | None
    profit_factor: float | None
    expectancy_r: float | None
    avg_win_r: float | None
    avg_loss_r: float | None
    payoff_ratio: float | None
    num_trades: int | None


class ScanResultOut(_ORMModel):
    id: int
    run_id: str | None
    as_of: dt.date
    symbol: str
    rank: int | None
    momentum_score: float | None
    passed: bool
    price: float | None
    dollar_volume: float | None
    relative_volume: float | None
    distance_from_ath: float | None
    atr: float | None
    sector: str | None


class OptimizationResultOut(_ORMModel):
    id: int
    study_name: str
    optimizer: str
    run_id: str | None
    objective: str
    objective_value: float | None
    sample: str
    fold: int | None
    sharpe: float | None
    cagr: float | None
    calmar: float | None
    max_drawdown: float | None
    expectancy_r: float | None
    num_trades: int | None
    is_selected: bool


class PerformanceOut(BaseModel):
    run_id: str | None
    n_trades: int
    trade_stats: dict[str, Any]
    performance: dict[str, Any] | None


class DashboardOut(BaseModel):
    """Aggregate snapshot powering the desktop Dashboard view."""

    latest_regime: RegimeOut | None
    latest_snapshot: PortfolioSnapshotOut | None
    top_scans: list[ScanResultOut]
    recent_trades: list[TradeOut]
    open_trades: int
    performance: PerformanceOut


class ConfigFileOut(BaseModel):
    """A configuration template/file for the Settings view (read-only)."""

    name: str
    content: str
    parsed: dict[str, Any] | None = None


class AttributionGroupOut(BaseModel):
    """Objective-first stats for one attribution slice (a sector, regime, reason)."""

    key: str
    num_trades: int
    expectancy_r: float | None
    profit_factor: float | None
    avg_winner_r: float | None
    avg_loser_r: float | None
    win_rate: float | None
    net_profit: float | None


class AttributionOut(BaseModel):
    """Performance sliced by sector, regime and exit reason (Analytics stage)."""

    run_id: str | None
    by_sector: list[AttributionGroupOut]
    by_regime: list[AttributionGroupOut]
    by_exit_reason: list[AttributionGroupOut]


class WatchlistEntryOut(_ORMModel):
    """One ranked watchlist row (Watchlists stage)."""

    id: int
    run_id: str | None
    as_of: dt.date
    generated_at: dt.datetime | None
    horizon: str
    horizon_label: str
    rank: int
    symbol: str
    conviction: float
    base_conviction: float
    band: str | None
    sector: str | None
    risk_rating: str
    horizon_days: int
    expected_move_pct: float | None
    expected_risk_pct: float | None
    reward_risk: float | None
    model_version: str
    config_hash: str | None


class WatchlistOut(BaseModel):
    """One horizon's ranked watchlist for a generation date."""

    horizon: str
    label: str
    as_of: dt.date | None
    entries: list[WatchlistEntryOut]


class WatchlistSetOut(BaseModel):
    """The full multi-horizon set (Today / This Week / This Month) for one date."""

    run_id: str | None
    as_of: dt.date | None
    horizons: list[WatchlistOut]


class WatchlistMoveOut(BaseModel):
    """A symbol present in both compared watchlists (rank/conviction delta)."""

    symbol: str
    base_rank: int
    against_rank: int
    rank_change: int  # positive = moved up the list (toward rank 1)
    base_conviction: float
    against_conviction: float
    conviction_change: float


class WatchlistComparisonOut(BaseModel):
    """Two watchlists for one horizon compared over time."""

    horizon: str
    base_date: dt.date
    against_date: dt.date
    added: list[WatchlistEntryOut]  # in `against`, not in `base`
    removed: list[WatchlistEntryOut]  # in `base`, not in `against`
    moved: list[WatchlistMoveOut]  # in both


class LifecycleOut(_ORMModel):
    """A persisted setup-lifecycle row (Lifecycle stage)."""

    id: int
    run_id: str | None
    symbol: str
    as_of: dt.date
    state: str
    previous_state: str | None
    state_since: dt.date
    reason: str | None
    conviction: float | None
    sector: str | None
    history: list[dict[str, Any]] | None
    model_version: str


class SignalQualityOut(BaseModel):
    """Signal-quality metrics for a group (overall / by source / by type)."""

    key: str
    n_signals: int
    n_evaluated: int
    win_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    avg_mfe: float | None
    avg_mae: float | None
    e_ratio: float | None
    payoff_ratio: float | None
    avg_holding_days: float | None
    avg_return_pct: float | None


class CalibrationBucketOut(BaseModel):
    label: str
    lo: float
    hi: float
    count: int
    avg_predicted: float | None
    actual_win_rate: float | None
    avg_r: float | None


class ConvictionAccuracyOut(BaseModel):
    pearson_conviction_r: float | None
    rank_auc: float | None
    brier_score: float | None
    monotonic_win_rate: bool


class MoveAccuracyOut(BaseModel):
    n: int
    mean_predicted: float | None
    mean_actual: float | None
    mean_abs_error: float | None
    bias: float | None


class EvaluatedSignalOut(BaseModel):
    """One generated signal joined to its outcome + predictions."""

    signal_id: int
    symbol: str
    ts: dt.datetime
    signal_type: str
    direction: str
    source: str
    conviction: float | None
    band: str | None
    predicted_move_pct: float | None
    closed: bool
    outcome: str  # win / loss / open / none
    r_multiple: float | None
    return_pct: float | None
    mfe: float | None
    mae: float | None
    holding_days: int | None


class SignalEvaluationOut(BaseModel):
    """The signal-evaluation dashboard payload."""

    run_id: str | None
    overall: SignalQualityOut
    calibration: list[CalibrationBucketOut]
    conviction_accuracy: ConvictionAccuracyOut
    move_accuracy: MoveAccuracyOut
    by_source: list[SignalQualityOut]
    by_type: list[SignalQualityOut]


class SectorHighlightOut(BaseModel):
    """The most attractive sector right now (by average conviction)."""

    sector: str
    avg_conviction: float
    count: int


class CommandPerformanceOut(BaseModel):
    """Compact recent-performance headline for the command center."""

    n_trades: int
    expectancy_r: float | None
    profit_factor: float | None
    win_rate: float | None
    net_pnl: float | None


class CommandCenterOut(BaseModel):
    """The Market Command Center: one aggregate for the landing page."""

    run_id: str | None
    as_of: dt.date | None  # newest BAR date (calendar) — data coverage
    updated_at: str | None = None  # when data was last pulled (UTC instant)
    regime: RegimeOut | None
    daily: list[WatchlistEntryOut]
    weekly: list[WatchlistEntryOut]
    monthly: list[WatchlistEntryOut]
    highest_conviction: ConvictionScoreOut | None
    best_reward_risk: WatchlistEntryOut | None
    top_sector: SectorHighlightOut | None
    portfolio_heat: float | None
    equity: float | None
    daily_pnl: float | None
    performance: CommandPerformanceOut
    watchlist_changes: WatchlistComparisonOut | None
    recent_triggered: list[LifecycleOut]


class LifecycleStateCount(BaseModel):
    state: str
    count: int


class LifecycleSummaryOut(BaseModel):
    """Per-state counts for the lifecycle pipeline view (canonical order)."""

    run_id: str | None
    total: int
    states: list[LifecycleStateCount]


class EligibilityFactorOut(BaseModel):
    """One scored options-eligibility factor."""

    name: str
    label: str
    status: str  # pass / warn / fail
    score: float
    weight: float
    detail: str


class OptionsEligibilityOut(BaseModel):
    """Whether a setup is suitable for options leverage (no contract is chosen)."""

    symbol: str
    eligible: bool
    confidence: float
    recommendation: str  # "Shares Preferred" | "Leverage Eligible"
    expected_move_pct: float | None
    factors: list[EligibilityFactorOut]
    summary: str


class TargetLevelOut(BaseModel):
    """One scale-out target in a trade plan."""

    label: str
    price: float
    r_multiple: float
    gain_pct: float
    scale_out_pct: float


class TradePlanOut(BaseModel):
    """A derived, read-only trade plan for a candidate (no order is placed)."""

    symbol: str
    entry: float
    stop: float
    stop_pct: float
    risk_per_share: float
    structural_support: float | None
    overhead_resistance: float | None
    targets: list[TargetLevelOut]
    blended_reward_risk: float
    final_reward_risk: float
    expected_holding_days_low: int
    expected_holding_days_high: int
    suggested_shares: int
    suggested_position_value: float
    suggested_portfolio_risk_pct: float
    suggested_risk_dollars: float
    risk_summary: list[str]
    reward_summary: list[str]
    failure_conditions: list[str]
    methodology: list[str]


class StructureCandidateOut(BaseModel):
    """One scored options structure (for transparency on the choice)."""

    structure: str
    display: str
    score: float
    components: dict[str, float]


class AvoidGateOut(BaseModel):
    """One AVOID gate's outcome."""

    name: str
    passed: bool
    detail: str


class ContractRecommendationOut(BaseModel):
    """The concrete (approximate) recommended contract."""

    structure: str
    display: str
    expiration_days: int
    strike: float
    delta: float
    short_strike: float | None
    short_delta: float | None
    risk_level: str
    contracts: int
    est_premium_per_contract: float
    max_loss: float
    target_profit: float
    suggested_allocation: float
    allocation_pct: float
    reward_to_risk: float | None


class OptionsRecommendationOut(BaseModel):
    """A defined-risk options recommendation for an eligible setup (no execution)."""

    symbol: str
    recommended: bool
    structure: str | None
    contract: ContractRecommendationOut | None
    expected_move_pct: float | None
    candidates: list[StructureCandidateOut]
    gates: list[AvoidGateOut]
    risk_disclosures: list[str]
    summary: str
    config_hash: str


class DataProviderOut(BaseModel):
    """The current data-provider selection (secrets reported only as present/absent)."""

    provider: str
    keys_present: dict[str, bool]
    valid_providers: list[str]


class DataProviderIn(BaseModel):
    """Update the data-provider selection and (optionally) its API-key secrets.

    A blank/omitted key leaves any existing secret untouched.
    """

    provider: str
    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    polygon_api_key: str | None = None


class ContributorOut(BaseModel):
    """One conviction factor's explainable contribution (Conviction stage).

    ``contribution`` is the factor's additive points toward the 0-100 score (always
    >= 0). ``impact`` is the *signed* effect relative to a neutral setup — positive
    factors lifted the score, negative ones dragged it — so the UI can show drivers
    and brakes (sums to ``score - neutral_baseline``).
    """

    name: str
    label: str
    raw: float | None
    weight: float
    contribution: float
    impact: float
    direction: str  # "positive" | "negative"


class ConvictionScoreOut(_ORMModel):
    """A persisted conviction score (Conviction stage)."""

    id: int
    run_id: str | None
    symbol: str
    as_of: dt.date
    score: float
    band: str
    model_version: str
    config_hash: str | None
    regime_score: float | None
    sector_strength: float | None
    relative_volume: float | None
    distance_to_ath: float | None
    trend_strength: float | None
    breadth: float | None
    momentum_score: float | None
    historical_edge: float | None
    breakdown: dict[str, Any] | None
    # The plain-language explanation persisted at scan time (Live Conviction).
    explanation: str | None = None
    # Explainability, computed at read time from the stored breakdown.
    contributors: list[ContributorOut] = []
    # A plain-language summary of why the score was assigned (stored, else computed).
    narrative: str | None = None


class OpportunityOut(_ORMModel):
    """A persisted Home-Run-opportunity classification (inspector + Conviction stage)."""

    id: int
    run_id: str | None
    symbol: str
    as_of: dt.date
    tier: str
    score: float
    new_ath: bool
    model_version: str
    config_hash: str | None
    new_ath_score: float | None
    momentum_score: float | None
    relative_volume: float | None
    regime_score: float | None
    sector_leadership: float | None
    historical_edge: float | None
    breakdown: dict[str, Any] | None


class AnalogsOut(BaseModel):
    """Historical analogs for a setup (Analogs stage)."""

    symbol: str | None
    regime: str | None
    sector: str | None
    sample_size: int
    expectancy_r: float | None
    win_rate: float | None
    avg_winner_r: float | None
    avg_loser_r: float | None
    trades: list[TradeOut]


class RiskBudgetOut(BaseModel):
    """A computed dynamic risk budget for a candidate (inspector)."""

    conviction_band: str | None
    opportunity_tier: str | None
    home_run: bool
    base_pct: float
    requested_pct: float
    granted_pct: float
    risk_dollars: float
    binding_constraint: str | None
    portfolio_heat_used: float
    portfolio_heat_after: float
    reasons: list[str]


class CandidateDetailOut(BaseModel):
    """One fetch that fills the Scan inspector — the candidate aggregate."""

    symbol: str
    scan: ScanResultOut | None
    conviction: ConvictionScoreOut | None
    opportunity: OpportunityOut | None
    analogs: AnalogsOut | None
    risk_budget: RiskBudgetOut | None


class RunOut(BaseModel):
    """A research run/workspace (run selector)."""

    run_id: str
    label: str | None = None


class RunDetailOut(_ORMModel):
    """A persisted session run (Paper screen: recent sessions + session details)."""

    run_id: str
    mode: str
    as_of: dt.date
    status: str
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    equity_start: float | None = None
    equity_end: float | None = None
    num_opened: int | None = None
    num_closed: int | None = None
    error: str | None = None


class AuditEventOut(_ORMModel):
    """An append-only audit event (Paper screen: recent audit events)."""

    id: int
    event_type: str
    ts: dt.datetime | None = None
    run_id: str | None = None
    symbol: str | None = None
    entity_type: str | None = None
    summary: str | None = None


class WatchlistCalibrationBucketOut(BaseModel):
    """One conviction bucket: avg conviction vs realised 1-month return."""

    label: str
    lo: float
    hi: float
    count: int
    avg_conviction: float
    avg_ret_1m: float | None
    hit_rate: float | None


class WatchlistScorecardOut(BaseModel):
    """Aggregate forward performance for one horizon's watchlist entries."""

    horizon: str
    label: str
    n: int
    n_complete: int
    avg_ret_1d: float | None
    avg_ret_1w: float | None
    avg_ret_1m: float | None
    hit_rate_1m: float | None
    avg_mfe: float | None
    avg_mae: float | None
    e_ratio: float | None
    avg_expected_move: float | None
    move_capture: float | None
    expected_move_hit_rate: float | None
    top_rank_avg_ret_1m: float | None
    rest_avg_ret_1m: float | None
    top_minus_rest: float | None


class WatchlistPredictionQualityOut(BaseModel):
    """How well a horizon's conviction/rank predicted realised returns."""

    horizon: str
    label: str
    n: int
    ic_conviction: float | None
    rank_ic: float | None
    hit_rate_1m: float | None
    monotonic_calibration: bool
    quality_score: float
    calibration: list[WatchlistCalibrationBucketOut]


class WatchlistPerformanceReportOut(BaseModel):
    """Watchlist-performance dashboard: scorecards + quality per horizon."""

    n_total: int
    n_complete: int
    generations: int
    best_horizon: str | None
    scorecards: list[WatchlistScorecardOut]
    quality: list[WatchlistPredictionQualityOut]
    generated_at: str


class WatchlistPerfEntryOut(_ORMModel):
    """One tracked watchlist entry (prediction + realised forward outcome)."""

    as_of: dt.date
    run_id: str | None
    horizon: str
    horizon_label: str
    symbol: str
    conviction: float
    rank: int
    expected_move_pct: float | None
    horizon_days: int
    reference_price: float
    ret_1d: float | None
    ret_1w: float | None
    ret_1m: float | None
    mfe: float | None
    mae: float | None
    bars_tracked: int
    complete: bool
    last_tracked_date: dt.date | None


class AuditConvictionBucketOut(BaseModel):
    """Win rate + expected value for one conviction bucket."""

    label: str
    lo: float
    hi: float
    n: int
    win_rate: float | None
    expected_value_r: float | None
    avg_predicted: float | None


class AuditFactorScoreOut(BaseModel):
    """A predictive factor's correlation with outcome + significance."""

    name: str
    ic: float | None
    p_value: float | None
    n: int
    significant: bool
    direction: str


class AuditCalibrationOut(BaseModel):
    """Conviction calibration report."""

    buckets: list[AuditConvictionBucketOut]
    brier_score: float | None
    monotonic_win_rate: bool
    ic: float | None
    p_value: float | None


class AuditAreaOut(BaseModel):
    """One subsystem's measured effectiveness."""

    area: str
    headline: str
    metrics: dict[str, float | None]
    p_value: float | None
    significant: bool


class SignalAuditOut(BaseModel):
    """The full signal-validation audit payload."""

    n_candidates: int
    n_with_conviction: int
    win_rate: float | None
    expectancy_r: float | None
    avg_reward_risk: float | None
    payoff_ratio: float | None
    max_drawdown_r: float | None
    conviction_buckets: list[AuditConvictionBucketOut]
    calibration: AuditCalibrationOut
    factor_scores: list[AuditFactorScoreOut]
    strongest_factors: list[AuditFactorScoreOut]
    weakest_factors: list[AuditFactorScoreOut]
    areas: list[AuditAreaOut]
    recommendations: list[str]
    caveats: list[str]
    config_hash: str
    generated_at: str


class RouteHealthOut(BaseModel):
    """The probe result for one API route."""

    method: str
    path: str
    classification: str  # PASS | 404 | 500 | FAIL | TIMEOUT | SKIPPED
    http_status: int | None
    detail: str | None = None


class ApiHealthReportOut(BaseModel):
    """Self-audit of every route: live-probe classification + summary counts."""

    total: int
    passed: int
    not_found: int
    server_errors: int
    failed: int
    timeouts: int
    skipped: int
    healthy: bool
    routes: list[RouteHealthOut]
    generated_at: str


class ErrorRecordOut(BaseModel):
    """One captured unhandled backend exception (secret-redacted)."""

    ts: str
    method: str
    path: str
    route: str | None = None
    route_path: str | None = None
    status: int
    exc_type: str
    exc_message: str
    query_params: dict[str, str] = {}
    path_params: dict[str, str] = {}
    traceback: str


class RecentErrorsOut(BaseModel):
    """The most recent backend exceptions for the Diagnostics screen."""

    count: int
    capacity: int
    errors: list[ErrorRecordOut]


class TrackedTradeOut(BaseModel):
    """One tracked trade born from a recommendation (original thesis + current state)."""

    trade_uid: str
    run_id: str | None
    symbol: str
    recommended_at: str | None
    instrument: str
    quantity: int | None
    entry_price: float
    stop_price: float
    targets: list[dict[str, Any]] | None
    conviction_score: float | None
    conviction_band: str | None
    regime: str | None
    sector: str | None
    thesis: str | None
    current_thesis_strength: float | None
    current_health_score: float | None
    trade_health: str | None
    status: str
    last_evaluated_at: str | None
    closed_at: str | None
    close_reason: str | None
    journal_trade_id: int | None
    realized_r: float | None
    realized_pnl: float | None
    realized_at: str | None
    # Mark-to-market (last scan-known price; computed on read, never stored)
    last_price: float | None = None
    unrealized_r: float | None = None
    unrealized_pnl: float | None = None
    distance_to_stop_pct: float | None = None


class TradeEvaluationOut(BaseModel):
    """One appended thesis evaluation for a tracked trade."""

    trade_uid: str
    run_id: str | None
    symbol: str
    evaluated_at: str | None
    current_conviction: float | None
    conviction_delta: float | None
    momentum_trend: str
    rs_trend: str
    volume_trend: str
    atr_expansion: float | None
    regime_at_entry: str | None
    regime_now: str | None
    regime_changed: bool
    sector_delta: float | None
    analog_delta: float | None
    thesis_strength: float
    thesis_stability: float
    health: str
    health_score: float | None
    health_breakdown: list[dict[str, Any]] | None
    action: str
    reasons: list[str] | None
    price: float
    stop_breached: bool
    explanation: dict[str, Any] | None


class TradeLifecycleSummaryOut(BaseModel):
    """Counts for the trade-lifecycle dashboard."""

    total: int
    by_status: dict[str, int]
    by_health: dict[str, int]
    by_action: dict[str, int]


class AdviceGradeOut(BaseModel):
    """One evaluation's advice graded against the trade's realized outcome."""

    trade_uid: str
    symbol: str
    evaluated_at: str | None
    action: str
    r_at_evaluation: float
    final_r: float
    remaining_r: float
    verdict: str


class AdviceActionStatsOut(BaseModel):
    """Hindsight accuracy for one action across all realized trades."""

    action: str
    n: int
    correct: int
    incorrect: int
    unclear: int
    accuracy: float | None
    avg_remaining_r: float | None


class AdviceReportOut(BaseModel):
    """How good the reevaluation advice has been, judged by realized outcomes."""

    trades_realized: int
    evaluations_graded: int
    overall_accuracy: float | None
    by_action: list[AdviceActionStatsOut]
    recent_grades: list[AdviceGradeOut]


class ManagementEventOut(BaseModel):
    """One automatic management action taken on a tracked trade."""

    at: str | None
    kind: str  # stop_loss | take_profit_scale | take_profit_final
    price: float | None
    fraction: float | None  # of the original position (1.0 = full close)
    target_index: int | None
    reason: str
    analysis: str  # the data-only "how and why" report
    evidence: dict[str, Any]
    health_at_decision: float | None
    conviction_at_decision: float | None


class ManagementReportOut(BaseModel):
    """How and why the system managed one tracked trade, end to end."""

    trade_uid: str
    symbol: str
    status: str
    entry_price: float
    stop_price: float
    targets: list[dict[str, Any]]
    recommended_at: str | None
    closed_at: str | None
    close_reason: str | None
    realized_r: float | None
    realized_pnl: float | None
    events: list[ManagementEventOut]
    summary: str  # one-paragraph plain-language wrap-up


class JournalEntryOut(BaseModel):
    """One entry in a trade's thesis journal (opened → evaluations → exited)."""

    at: str | None
    label: str
    detail: str | None
    health_score: float | None
    conviction: float | None
    action: str | None


class ManagementAnalyticsOut(BaseModel):
    """Metrics that grade the management logic itself (not win rate, not profit)."""

    trades_tracked: int
    avg_conviction_decay: float | None
    avg_trade_health: float | None
    avg_holding_period_days: float | None
    max_thesis_age_days: float | None
    most_successful_health: dict[str, Any] | None
    best_exits: list[AdviceGradeOut]
    worst_exits: list[AdviceGradeOut]
    avg_conviction_recovery: float | None
    avg_stop_raises: float | None
    avg_stop_lowers: float | None
    avg_health_before_exit: float | None


class DaemonStatusOut(BaseModel):
    """Live status of the continuous market daemon."""

    running: bool
    paused: bool
    scanning_now: bool
    market_state: str
    scan_interval_seconds: float
    closed_interval_seconds: float
    cycles: int
    failures: int
    consecutive_failures: int
    last_scan_at: str | None
    last_error: str | None
    next_wake_at: str | None
    seconds_to_next_wake: float | None
    version: int
    last_result: dict[str, Any] | None
    cached_symbols: int


class DaemonEventOut(BaseModel):
    """One published daemon event (scan complete / error / control)."""

    model_config = ConfigDict(extra="allow")

    ts: str
    kind: str
    message: str


class ScanSnapshotOut(BaseModel):
    """One immutable scan snapshot (header)."""

    id: int
    scan_ts: str | None
    run_id: str | None
    market_state: str | None
    candidates: int


class ScanSnapshotDetailOut(ScanSnapshotOut):
    """A snapshot with its full frozen payload (replay)."""

    payload: dict[str, Any]


class ScanDeltaOut(BaseModel):
    """One changed metric between two scans (UPGRADE / DOWNGRADE)."""

    scan_ts: str | None = None
    run_id: str | None = None
    prev_scan_ts: str | None = None
    symbol: str | None
    metric: str
    previous_value: float | None
    new_value: float | None
    previous_text: str | None
    new_text: str | None
    delta: float | None
    direction: str
    reason: str


class AlertOut(BaseModel):
    """One live alert (deduplicated at write time)."""

    id: int
    ts: str | None
    run_id: str | None
    symbol: str | None
    severity: str
    kind: str
    title: str
    description: str


class ActivityOut(BaseModel):
    """One market-activity feed entry."""

    id: int
    ts: str | None
    run_id: str | None
    symbol: str | None
    category: str
    text: str
    payload: dict[str, Any] | None


class ScanStatOut(BaseModel):
    """One scan's performance record."""

    id: int
    scan_ts: str | None
    run_id: str | None
    duration_ms: float
    symbols_processed: int
    symbols_failed: int
    provider_latency_ms: float | None
    db_writes: int
    convictions_generated: int
    watchlists_generated: int
    alerts_generated: int
    deltas_generated: int
    activities_generated: int
    symbols_skipped: int | None
    symbols_recomputed: int | None
    cache_hit_rate: float | None
    memory_mb: float | None
    cpu_percent: float | None
    degraded: bool


class ClockOut(BaseModel):
    """The live clock: market time/status + countdowns (local time is client-side)."""

    state: str
    utc: str
    market_time: str
    market_tz: str
    next_market_open: str
    next_market_close: str
    next_premarket: str
    seconds_to_market_open: float
    seconds_to_market_close: float
    seconds_to_premarket: float
    seconds_to_next_scan: float | None
    daemon_running: bool


class BarOut(BaseModel):
    """One daily OHLCV bar for charting."""

    ts: str  # calendar date (YYYY-MM-DD)
    open: float
    high: float
    low: float
    close: float
    volume: float | None


class BarsOut(BaseModel):
    """A symbol's chartable bars + where they came from."""

    symbol: str
    source: str  # cache | live | stale-cache
    bars: list[BarOut]


class EquityPointOut(BaseModel):
    """One point on a persisted backtest equity curve."""

    ts: str  # calendar date (YYYY-MM-DD)
    equity: float


class BacktestTradeOut(BaseModel):
    """One closed trade from a persisted backtest run."""

    symbol: str
    entry_date: str | None
    exit_date: str | None
    pnl: float
    r_multiple: float
    holding_days: int
    exit_reason: str | None


class BacktestDetailOut(BaseModel):
    """Equity curve + trade list persisted for one backtest run."""

    run_id: str
    equity_curve: list[EquityPointOut]
    trades: list[BacktestTradeOut]
    benchmark_curve: list[EquityPointOut] = []  # SPY buy-and-hold overlay (same start equity)


class EarningsOut(BaseModel):
    """A symbol's next scheduled earnings (advisory; nulls when unknown)."""

    symbol: str
    earnings_date: str | None  # calendar date (YYYY-MM-DD)
    days_until: int | None


class CorporateActionsOut(BaseModel):
    """A symbol's upcoming corporate-actions calendar (advisory; nulls = unknown)."""

    symbol: str
    as_of: str  # calendar date (YYYY-MM-DD)
    earnings_date: str | None
    days_until_earnings: int | None
    ex_dividend_date: str | None
    days_until_ex_dividend: int | None
    dividend_payment_date: str | None
    dividend_amount: float | None  # annualized $ per share
    source: str


class OrderFillOut(BaseModel):
    """One persisted execution against an order."""

    order_id: str
    symbol: str
    side: str
    shares: int
    price: float
    fees: float
    ts: str | None


class OrderOut(BaseModel):
    """One persisted broker order with its fills (the execution audit trail)."""

    order_id: str
    run_id: str | None
    symbol: str
    side: str
    quantity: int
    order_type: str
    time_in_force: str
    limit_price: float | None
    stop_price: float | None
    status: str
    filled_quantity: int
    avg_fill_price: float | None
    total_fees: float
    reject_reason: str | None
    created_ts: str | None
    fills: list[OrderFillOut]
