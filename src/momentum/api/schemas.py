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
