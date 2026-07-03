"""Live-trading safety gates — every gate rejects, every reason named."""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.brokerage import (
    BrokerCapabilities,
    GateInputs,
    GateReport,
    OrderRouter,
    PaperBrokerAdapter,
    PaperBrokerage,
    evaluate_gates,
)
from momentum.brokerage.types import OrderTicket
from momentum.core.enums import Side
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base

NOW = dt.datetime(2026, 7, 1, 15, 0, tzinfo=dt.UTC)  # Wednesday 11:00 ET (open)


def _green() -> GateInputs:
    """Inputs that clear every gate."""
    return GateInputs(
        ts=NOW,
        market_state="regular",
        data_age_minutes=3.0,
        data_stale=False,
        last_scan_age_minutes=5.0,
        risk_engine_healthy=True,
        risk_engine_detail="risk engine constructed",
        broker_healthy=True,
        broker_detail="broker answered",
        buying_power=100_000.0,
        estimated_cost=10_000.0,
        open_positions=3,
        symbol_sector="Technology",
        sector_exposure_pct=18.0,
        equity=100_000.0,
        daily_pnl=-500.0,
        stop_price=95.0,
        entry_price=100.0,
        quantity=100,
    )


def test_all_green_passes_every_gate() -> None:
    report = evaluate_gates(_green())
    assert report.passed, report.reasons
    assert len(report.results) == 10
    assert report.failures == ()
    assert report.reasons == ""


@pytest.mark.parametrize(
    ("override", "gate", "phrase"),
    [
        ({"market_state": "closed"}, "market_open", "regular session"),
        ({"data_age_minutes": 90.0}, "fresh_market_data", "stale or missing"),
        ({"data_stale": True}, "fresh_market_data", "stale or missing"),
        ({"data_age_minutes": None}, "fresh_market_data", "stale or missing"),
        ({"last_scan_age_minutes": None}, "current_scan", "no recent completed scan"),
        ({"last_scan_age_minutes": 120.0}, "current_scan", "no recent completed scan"),
        (
            {"risk_engine_healthy": False, "risk_engine_detail": "config broken"},
            "risk_engine",
            "config broken",
        ),
        (
            {"broker_healthy": False, "broker_detail": "broker unreachable: timeout"},
            "broker_health",
            "unreachable",
        ),
        ({"estimated_cost": 200_000.0}, "buying_power", "insufficient"),
        ({"estimated_cost": None}, "buying_power", "unverifiable"),
        ({"open_positions": 8}, "position_limits", "position limit reached"),
        ({"sector_exposure_pct": 45.0}, "sector_concentration", "concentrate"),
        ({"daily_pnl": -5_000.0}, "daily_loss_limit", "loss limit is breached"),
        ({"stop_price": None}, "max_risk", "protective stop"),
        ({"quantity": 5_000}, "max_risk", "protective stop"),
    ],
)
def test_each_gate_rejects_with_the_exact_reason(
    override: dict[str, object], gate: str, phrase: str
) -> None:
    inputs = dataclasses.replace(_green(), **override)  # type: ignore[arg-type]
    report = evaluate_gates(inputs)
    assert not report.passed
    failed = {r.gate for r in report.failures}
    assert gate in failed, f"expected {gate} to fail, got {failed}"
    finding = next(r for r in report.failures if r.gate == gate)
    assert phrase in finding.detail
    assert gate in report.reasons  # the rejection names the gate


def test_a_multi_failure_report_names_every_reason() -> None:
    inputs = dataclasses.replace(
        _green(), market_state="closed", data_stale=True, open_positions=20, stop_price=None
    )
    report = evaluate_gates(inputs)
    failed = {r.gate for r in report.failures}
    assert {"market_open", "fresh_market_data", "position_limits", "max_risk"} <= failed
    for gate in ("market_open", "fresh_market_data", "position_limits", "max_risk"):
        assert gate in report.reasons  # ALL failures reported, not just the first


# --------------------------------------------------------------------------- #
# router enforcement
# --------------------------------------------------------------------------- #
@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _live_adapter(factory: sessionmaker[Session]) -> PaperBrokerAdapter:
    """A live-mode adapter (the venue is simulated; the MODE drives the gates)."""

    class LiveAdapter(PaperBrokerAdapter):
        @property
        def name(self) -> str:
            return "fake-live"

    return LiveAdapter(
        PaperBrokerage(factory, clock=lambda: NOW),
        capabilities=BrokerCapabilities(broker="fake-live", mode="live"),
    )


def _ticket() -> OrderTicket:
    return OrderTicket(
        client_order_id="live-1",
        account_id="primary",
        symbol="AAPL",
        side=Side.LONG,
        quantity=10,
    )


def test_live_adapter_without_gatekeeper_refuses_everything(
    factory: sessionmaker[Session],
) -> None:
    router = OrderRouter()  # fail-safe: no gatekeeper configured
    router.register(_live_adapter(factory), default=True)
    report = router.submit(_ticket(), ts=NOW)
    assert report.accepted is False and report.order is None
    assert report.reason is not None and "fail-safe" in report.reason
    assert router.routing_log()[0]["accepted"] is False


def test_failing_gates_reject_before_the_venue(factory: sessionmaker[Session]) -> None:
    def gatekeeper(ticket: OrderTicket, adapter: object) -> GateReport:
        return evaluate_gates(dataclasses.replace(_green(), market_state="closed"))

    router = OrderRouter(live_gatekeeper=gatekeeper)
    adapter = _live_adapter(factory)
    router.register(adapter, default=True)
    report = router.submit(_ticket(), ts=NOW)
    assert report.accepted is False
    assert report.reason is not None
    assert "live order rejected" in report.reason and "market_open" in report.reason
    assert adapter.get_orders() == []  # the venue never saw the ticket


def test_passing_gates_let_the_order_through(factory: sessionmaker[Session]) -> None:
    def gatekeeper(ticket: OrderTicket, adapter: object) -> GateReport:
        return evaluate_gates(_green())

    router = OrderRouter(live_gatekeeper=gatekeeper)
    router.register(_live_adapter(factory), default=True)
    report = router.submit(_ticket(), ts=NOW)
    assert report.accepted is True
    assert report.order is not None and report.order.status.value == "working"


def test_paper_mode_is_never_gated(factory: sessionmaker[Session]) -> None:
    """The gates guard LIVE money; the paper venue trades freely."""
    router = OrderRouter()  # no gatekeeper — paper must still work
    router.register(PaperBrokerAdapter(PaperBrokerage(factory, clock=lambda: NOW)), default=True)
    report = router.submit(_ticket(), ts=NOW)
    assert report.accepted is True
