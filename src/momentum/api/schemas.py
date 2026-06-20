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
    as_of: dt.date | None
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
    # Explainability, computed at read time from the stored breakdown.
    contributors: list[ContributorOut] = []
    # A plain-language summary of why the score was assigned.
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
