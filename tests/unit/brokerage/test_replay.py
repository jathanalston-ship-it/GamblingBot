"""Portfolio-replay tests: state reconstruction from the immutable trail."""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session, sessionmaker

from momentum.api import brokerage_replay_service as replay
from momentum.brokerage import PaperBrokerage
from momentum.brokerage.types import BracketSpec, OrderTicket
from momentum.core.enums import Side
from tests.unit.brokerage.conftest import NOW, quote

T1 = NOW + dt.timedelta(minutes=10)
T2 = NOW + dt.timedelta(minutes=20)


def _run_session(broker: PaperBrokerage) -> None:
    """Entry with bracket at NOW, fills at NOW, target exit at T2."""
    broker.place_order(
        OrderTicket(
            client_order_id="entry",
            account_id="primary",
            symbol="AAPL",
            side=Side.LONG,
            quantity=100,
            bracket=BracketSpec(take_profit_limit=110.0, stop_loss_stop=95.0),
        ),
        ts=NOW,
    )
    broker.process_tick({"AAPL": quote()}, ts=NOW)
    broker.process_tick({"AAPL": quote(last=105.0, ts=T1)}, ts=T1)
    broker.process_tick({"AAPL": quote(last=111.0, ts=T2)}, ts=T2)


def test_timestamps_cover_the_session(
    broker: PaperBrokerage, factory: sessionmaker[Session]
) -> None:
    _run_session(broker)
    stamps = replay.timestamps(factory)
    assert len(stamps) >= 4  # opened, fill, marks, exit fill
    assert stamps == sorted(stamps, key=lambda s: str(s["ts"]))
    assert all({"ts", "event", "equity"} <= set(s) for s in stamps)


def test_state_before_entry_is_flat(broker: PaperBrokerage, factory: sessionmaker[Session]) -> None:
    _run_session(broker)
    state = replay.state_at(factory, NOW - dt.timedelta(hours=1))
    assert state["positions"] == []
    assert state["orders"] == []
    assert state["fills"] == []


def test_state_mid_session_shows_open_position_and_working_children(
    broker: PaperBrokerage, factory: sessionmaker[Session]
) -> None:
    _run_session(broker)
    state = replay.state_at(factory, T1 + dt.timedelta(minutes=1))
    assert len(state["positions"]) == 1
    assert state["positions"][0]["symbol"] == "AAPL"
    statuses = {o["order_id"]: o["status"] for o in state["orders"]}
    assert statuses["entry"] == "filled"
    assert statuses["entry:take_profit"] == "working"
    assert statuses["entry:stop_loss"] == "working"
    assert state["account"] is not None
    assert state["account"]["equity"] > 0


def test_state_at_end_shows_flat_book_and_oco_cancel(
    broker: PaperBrokerage, factory: sessionmaker[Session]
) -> None:
    _run_session(broker)
    state = replay.state_at(factory, T2 + dt.timedelta(minutes=1))
    assert state["positions"] == []  # closed at the target
    statuses = {o["order_id"]: o["status"] for o in state["orders"]}
    assert statuses["entry:take_profit"] == "filled"
    assert statuses["entry:stop_loss"] == "cancelled"
    assert len(state["fills"]) == 2  # entry + exit


def test_replay_is_read_only(broker: PaperBrokerage, factory: sessionmaker[Session]) -> None:
    _run_session(broker)
    before = replay.timestamps(factory)
    replay.state_at(factory, T1)
    replay.state_at(factory, T2)
    assert replay.timestamps(factory) == before  # replaying changed nothing


def test_partial_reduce_replays_point_in_time_quantities(
    broker: PaperBrokerage, factory: sessionmaker[Session]
) -> None:
    """A position later reduced must replay with its EARLIER size, not the
    current row's — quantities and average cost come from the fill trail."""
    broker.place_order(
        OrderTicket(
            client_order_id="buy100",
            account_id="primary",
            symbol="AAPL",
            side=Side.LONG,
            quantity=100,
        ),
        ts=NOW,
    )
    broker.process_tick({"AAPL": quote()}, ts=NOW)
    broker.close_position("primary", "AAPL", quantity=40, ts=T1)
    broker.process_tick({"AAPL": quote(last=104.0, ts=T1)}, ts=T1)

    before = replay.state_at(factory, NOW + dt.timedelta(minutes=5))
    assert before["positions"][0]["quantity"] == 100  # NOT the current 60
    assert before["positions"][0]["realized_pnl"] == 0.0

    after = replay.state_at(factory, T1 + dt.timedelta(minutes=1))
    assert after["positions"][0]["quantity"] == 60
    assert after["positions"][0]["realized_pnl"] > 0  # 40 sold above cost
    assert after["positions"][0]["avg_cost"] == before["positions"][0]["avg_cost"]
    assert "last execution" in after["positions"][0]["priced_at"]
