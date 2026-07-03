"""HTTP-surface tests for the brokerage endpoints (offline)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api.app import create_app
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base


@pytest.fixture
def client() -> TestClient:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = create_session_factory(engine)
    return TestClient(create_app(session_factory=factory))


def test_account_bootstraps_on_first_read(client: TestClient) -> None:
    body = client.get("/brokerage/account").json()
    assert body["account_id"] == "primary"
    assert body["cash"] == 100_000.0
    assert body["buying_power"] == 100_000.0
    assert body["trade_count"] == 0


def test_place_get_cancel_order_flow(client: TestClient) -> None:
    placed = client.post(
        "/brokerage/orders",
        json={
            "symbol": "aapl",
            "quantity": 50,
            "order_type": "limit",
            "limit_price": 90.0,
            "client_order_id": "web-1",
        },
    )
    assert placed.status_code == 201
    assert placed.json()["status"] == "working"

    fetched = client.get("/brokerage/orders/web-1").json()
    assert fetched["symbol"] == "AAPL"
    assert [e["to_status"] for e in fetched["events"]] == ["submitted", "accepted", "working"]

    modified = client.patch("/brokerage/orders/web-1", json={"limit_price": 92.0}).json()
    assert modified["limit_price"] == 92.0

    cancelled = client.delete("/brokerage/orders/web-1").json()
    assert cancelled["status"] == "cancelled"
    # A second cancel is an illegal transition -> 409, not a 500.
    assert client.delete("/brokerage/orders/web-1").status_code == 409


def test_validation_errors_are_400s(client: TestClient) -> None:
    res = client.post(
        "/brokerage/orders", json={"symbol": "AAPL", "quantity": 10, "order_type": "limit"}
    )
    assert res.status_code == 400
    assert "limit price" in res.json()["detail"]


def test_reads_cover_the_full_surface(client: TestClient) -> None:
    for path in (
        "/brokerage/portfolio",
        "/brokerage/buying-power",
        "/brokerage/positions",
        "/brokerage/orders",
        "/brokerage/fills",
        "/brokerage/history",
    ):
        assert client.get(path).status_code == 200, path
    portfolio = client.get("/brokerage/portfolio").json()
    assert set(portfolio) == {"account", "positions", "open_orders"}
    assert client.get("/brokerage/orders/nope").status_code == 404
    assert client.post("/brokerage/positions/AAPL/close").status_code == 409  # nothing held
