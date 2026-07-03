"""OrderRouter / adapter / capabilities / sync tests.

The architectural promise under test: the decision engine emits intent,
the router owns venue fit, and swapping paper for live is routing
configuration — never decision-code changes.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.brokerage import (
    AccountSync,
    BrokerAdapter,
    BrokerCapabilities,
    Brokerage,
    OrderRouter,
    PaperBrokerAdapter,
    PaperBrokerage,
    PositionSync,
    Quote,
    paper_capabilities,
)
from momentum.brokerage.types import OrderTicket
from momentum.core.enums import OrderType, Side
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base
from momentum.persistence.models.broker import BrokerOrderRow

NOW = dt.datetime(2026, 7, 1, 14, 0, tzinfo=dt.UTC)


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.fixture
def adapter(factory: sessionmaker[Session]) -> PaperBrokerAdapter:
    return PaperBrokerAdapter(PaperBrokerage(factory, clock=lambda: NOW))


def _ticket(order_type: OrderType = OrderType.MARKET, **kwargs: object) -> OrderTicket:
    base: dict[str, object] = {
        "client_order_id": "t-1",
        "account_id": "primary",
        "symbol": "AAPL",
        "side": Side.LONG,
        "quantity": 10,
        "order_type": order_type,
    }
    if order_type is OrderType.TRAILING_STOP:
        base["trail_percent"] = 5.0
    if order_type is OrderType.LIMIT:
        base["limit_price"] = 100.0
    base.update(kwargs)
    return OrderTicket(**base)  # type: ignore[arg-type]


def test_adapter_conforms_to_the_brokerage_protocol(adapter: PaperBrokerAdapter) -> None:
    assert isinstance(adapter, Brokerage)
    assert isinstance(adapter, BrokerAdapter)
    assert adapter.capabilities.mode == "paper"


def test_router_routes_to_the_default_adapter(adapter: PaperBrokerAdapter) -> None:
    router = OrderRouter()
    router.register(adapter, default=True)
    report = router.submit(_ticket(), ts=NOW)
    assert report.accepted is True
    assert report.broker == "paper"
    assert report.mode == "paper"
    assert report.order is not None and report.order.status.value == "working"
    log = router.routing_log()
    assert log and log[0]["action"] == "place" and log[0]["accepted"] is True


def test_unsupported_order_is_refused_before_the_venue_sees_it(
    factory: sessionmaker[Session],
) -> None:
    """A venue that declares no trailing stops never receives one.

    (Simulation mode: live mode additionally sits behind the safety gates,
    proven in test_safety_gates.py — here the capability check is isolated.)"""
    limited = BrokerCapabilities(
        broker="limited-live",
        mode="simulation",
        order_types=frozenset({OrderType.MARKET, OrderType.LIMIT}),
    )
    adapter = PaperBrokerAdapter(PaperBrokerage(factory, clock=lambda: NOW), capabilities=limited)
    router = OrderRouter()
    router.register(adapter, default=True)

    report = router.submit(_ticket(OrderType.TRAILING_STOP), ts=NOW)
    assert report.accepted is False
    assert report.order is None
    assert report.reason is not None and "trailing_stop" in report.reason
    with factory() as session:
        assert session.query(BrokerOrderRow).count() == 0  # the venue never saw it
    assert router.routing_log()[0]["accepted"] is False


def test_venue_rejection_flows_back_through_the_report(
    adapter: PaperBrokerAdapter,
) -> None:
    router = OrderRouter()
    router.register(adapter)
    report = router.submit(_ticket(side=Side.SHORT), ts=NOW)  # selling what we don't hold
    assert report.accepted is False
    assert report.reason is not None and "cannot sell" in report.reason
    assert report.order is not None and report.order.status.value == "rejected"


def test_router_supports_multiple_brokers_by_name(factory: sessionmaker[Session]) -> None:
    paper = PaperBrokerAdapter(PaperBrokerage(factory, clock=lambda: NOW))
    sim = PaperBrokerAdapter(
        PaperBrokerage(factory, clock=lambda: NOW),
        capabilities=BrokerCapabilities(broker="sim", mode="simulation"),
    )

    class SimAdapter(PaperBrokerAdapter):
        @property
        def name(self) -> str:
            return "sim"

    sim = SimAdapter(PaperBrokerage(factory, clock=lambda: NOW), capabilities=sim.capabilities)
    router = OrderRouter()
    router.register(paper, default=True)
    router.register(sim)
    assert router.brokers == ["paper", "sim"]
    assert router.default_broker == "paper"
    report = router.submit(_ticket(client_order_id="sim-1"), broker="sim", ts=NOW)
    assert report.broker == "sim" and report.mode == "simulation"
    with pytest.raises(KeyError):
        router.adapter("does-not-exist")


def test_position_and_account_sync_reflect_the_venue(
    adapter: PaperBrokerAdapter,
) -> None:
    router = OrderRouter()
    router.register(adapter)
    router.submit(_ticket(), ts=NOW)
    quote = Quote(symbol="AAPL", ts=NOW, bid=99.9, ask=100.1, last=100.0, volume=5e6)
    adapter.venue.process_tick({"AAPL": quote}, ts=NOW)

    positions = PositionSync(adapter).snapshot()
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL" and positions[0].quantity == 10

    account = AccountSync(adapter).snapshot()
    assert account.fills == 1
    assert account.cash < adapter.venue.config.account.starting_cash  # paid for the shares
    assert account.buying_power >= 0


def test_decision_engines_never_import_a_concrete_broker() -> None:
    """Zero-changes-for-new-brokers, enforced: scanner, trade manager, risk,
    conviction and portfolio code must not name any concrete venue."""
    src = Path(__file__).resolve().parents[3] / "src" / "momentum"
    forbidden = ("PaperBrokerage", "PaperBrokerAdapter", "AlpacaBroker", "alpaca")
    for package in ("universe", "trade_lifecycle", "risk", "conviction", "portfolio"):
        for path in (src / package).rglob("*.py"):
            text = path.read_text()
            for name in forbidden:
                assert name not in text, f"{path} references concrete broker {name!r}"


def test_capability_serialization_and_paper_defaults() -> None:
    caps = paper_capabilities()
    payload = caps.to_dict()
    assert payload["broker"] == "paper" and payload["mode"] == "paper"
    assert "market" in payload["order_types"] and payload["supports_brackets"] is True
    assert caps.rejection_reason(_ticket()) is None
    huge = _ticket(quantity=2_000_000)
    reason = caps.rejection_reason(huge)
    assert reason is not None and "maximum" in reason
