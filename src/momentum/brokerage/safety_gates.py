"""Live trading safety gates — non-negotiable checks before any live order.

Ten gates run before a live order may leave the router. **Every** gate is
evaluated (a failing report names *all* failures, not just the first), any
failure rejects the order with exact reasons, and everything is logged.
The gate chain is pure — the service layer gathers the evidence and the
router enforces the verdict for any adapter whose declared capability mode
is ``live``. Fail-safe default: a live adapter with **no** gatekeeper
configured can never receive an order at all.

| Gate | Verifies |
| ---- | -------- |
| market_open           | the ET schedule says the regular session is open |
| fresh_market_data     | the newest scan's data age is inside the freshness window |
| current_scan          | a completed scan exists and is recent |
| risk_engine           | the risk engine is constructible and not circuit-broken |
| broker_health         | the venue answered a live account read |
| buying_power          | estimated cost fits inside available buying power |
| position_limits       | the book has room under max open positions |
| sector_concentration  | the ticket's sector stays under its exposure cap |
| daily_loss_limit      | today's P&L has not breached the daily loss limit |
| max_risk              | the order carries a protective stop and risks <= the cap |
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SafetyGateConfig(BaseModel):
    """The non-negotiable limits (immutable, strict defaults)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_data_age_minutes: float = Field(15.0, gt=0)
    max_scan_age_minutes: float = Field(30.0, gt=0)
    max_open_positions: int = Field(8, ge=1)
    max_sector_concentration_pct: float = Field(30.0, gt=0, le=100)
    daily_loss_limit_pct: float = Field(3.0, gt=0, le=100)
    max_trade_risk_pct: float = Field(2.0, gt=0, le=100)


@dataclass(frozen=True, slots=True)
class GateInputs:
    """Everything the gates need, gathered by the service layer."""

    ts: dt.datetime
    market_state: str  # premarket | regular | after_hours | closed
    data_age_minutes: float | None  # None = no scan metadata at all
    data_stale: bool
    last_scan_age_minutes: float | None  # None = no completed scan
    risk_engine_healthy: bool
    risk_engine_detail: str
    broker_healthy: bool
    broker_detail: str
    buying_power: float
    estimated_cost: float | None  # None = no price reference
    open_positions: int
    symbol_sector: str | None
    sector_exposure_pct: float  # post-trade exposure of the ticket's sector
    equity: float
    daily_pnl: float
    stop_price: float | None  # the protective stop the order carries
    entry_price: float | None
    quantity: int


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: str
    passed: bool
    measured: str
    threshold: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "passed": self.passed,
            "measured": self.measured,
            "threshold": self.threshold,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class GateReport:
    """The full verdict: every gate, every reason."""

    ts: dt.datetime
    results: tuple[GateResult, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> tuple[GateResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    @property
    def reasons(self) -> str:
        return "; ".join(f"{r.gate}: {r.detail}" for r in self.failures)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "passed": self.passed,
            "reasons": self.reasons or None,
            "results": [r.to_dict() for r in self.results],
        }


def evaluate_gates(inputs: GateInputs, config: SafetyGateConfig | None = None) -> GateReport:
    """Run every gate; a failing report carries every failure. Pure."""
    cfg = config or SafetyGateConfig()
    results: list[GateResult] = []

    results.append(
        GateResult(
            gate="market_open",
            passed=inputs.market_state == "regular",
            measured=f"market is '{inputs.market_state}'",
            threshold="regular session only",
            detail="live orders are only routed while the regular session is open"
            if inputs.market_state != "regular"
            else "regular session open",
        )
    )

    fresh = (
        inputs.data_age_minutes is not None
        and not inputs.data_stale
        and inputs.data_age_minutes <= cfg.max_data_age_minutes
    )
    results.append(
        GateResult(
            gate="fresh_market_data",
            passed=fresh,
            measured=(
                f"data age {inputs.data_age_minutes:.1f}m"
                + (" (stale)" if inputs.data_stale else "")
                if inputs.data_age_minutes is not None
                else "no scan metadata"
            ),
            threshold=f"<= {cfg.max_data_age_minutes:.0f}m and not stale",
            detail="market data is fresh"
            if fresh
            else "market data is stale or missing — a live order cannot be priced off old data",
        )
    )

    scan_ok = (
        inputs.last_scan_age_minutes is not None
        and inputs.last_scan_age_minutes <= cfg.max_scan_age_minutes
    )
    results.append(
        GateResult(
            gate="current_scan",
            passed=scan_ok,
            measured=(
                f"last completed scan {inputs.last_scan_age_minutes:.1f}m ago"
                if inputs.last_scan_age_minutes is not None
                else "no completed scan"
            ),
            threshold=f"<= {cfg.max_scan_age_minutes:.0f}m",
            detail="a current scan backs this decision"
            if scan_ok
            else "no recent completed scan — the decision context is out of date",
        )
    )

    results.append(
        GateResult(
            gate="risk_engine",
            passed=inputs.risk_engine_healthy,
            measured=inputs.risk_engine_detail,
            threshold="risk engine healthy",
            detail=inputs.risk_engine_detail,
        )
    )

    results.append(
        GateResult(
            gate="broker_health",
            passed=inputs.broker_healthy,
            measured=inputs.broker_detail,
            threshold="broker answering",
            detail=inputs.broker_detail,
        )
    )

    affordable = inputs.estimated_cost is not None and (
        inputs.estimated_cost <= inputs.buying_power
    )
    results.append(
        GateResult(
            gate="buying_power",
            passed=affordable,
            measured=(
                f"cost ~{inputs.estimated_cost:,.0f} vs buying power {inputs.buying_power:,.0f}"
                if inputs.estimated_cost is not None
                else f"no price reference (buying power {inputs.buying_power:,.0f})"
            ),
            threshold="estimated cost <= buying power",
            detail="sufficient buying power"
            if affordable
            else "insufficient (or unverifiable) buying power for a live order",
        )
    )

    room = inputs.open_positions < cfg.max_open_positions
    results.append(
        GateResult(
            gate="position_limits",
            passed=room,
            measured=f"{inputs.open_positions} open positions",
            threshold=f"< {cfg.max_open_positions}",
            detail="book has room" if room else "position limit reached — no new live entries",
        )
    )

    sector_ok = inputs.sector_exposure_pct <= cfg.max_sector_concentration_pct
    results.append(
        GateResult(
            gate="sector_concentration",
            passed=sector_ok,
            measured=(
                f"{inputs.symbol_sector or 'unknown sector'} would be "
                f"{inputs.sector_exposure_pct:.1f}% of equity"
            ),
            threshold=f"<= {cfg.max_sector_concentration_pct:.0f}%",
            detail="sector exposure inside the cap"
            if sector_ok
            else "this order would concentrate too much of the book in one sector",
        )
    )

    loss_limit = cfg.daily_loss_limit_pct / 100.0 * max(inputs.equity, 1e-9)
    loss_ok = inputs.daily_pnl > -loss_limit
    results.append(
        GateResult(
            gate="daily_loss_limit",
            passed=loss_ok,
            measured=f"daily P&L {inputs.daily_pnl:,.0f}",
            threshold=f"> -{loss_limit:,.0f} ({cfg.daily_loss_limit_pct:.1f}% of equity)",
            detail="inside the daily loss limit"
            if loss_ok
            else "the daily loss limit is breached — live trading halts for the day",
        )
    )

    risk_pct: float | None = None
    if (
        inputs.stop_price is not None
        and inputs.entry_price is not None
        and inputs.entry_price > inputs.stop_price > 0
        and inputs.equity > 0
    ):
        risk_pct = (
            (inputs.entry_price - inputs.stop_price) * inputs.quantity / inputs.equity * 100.0
        )
    risk_ok = risk_pct is not None and risk_pct <= cfg.max_trade_risk_pct
    results.append(
        GateResult(
            gate="max_risk",
            passed=risk_ok,
            measured=(
                f"trade risks {risk_pct:.2f}% of equity"
                if risk_pct is not None
                else "no protective stop on the order"
            ),
            threshold=f"stop required; risk <= {cfg.max_trade_risk_pct:.1f}%",
            detail="risk verified against the stop"
            if risk_ok
            else "a live order must carry a protective stop and risk no more "
            f"than {cfg.max_trade_risk_pct:.1f}% of equity",
        )
    )

    return GateReport(ts=inputs.ts, results=tuple(results))
