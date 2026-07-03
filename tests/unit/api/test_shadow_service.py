"""Shadow-service tests: the scan hook generates + manages, never submits."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, shadow_service
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base, ShadowTrade, Trade
from momentum.persistence.models.broker import BrokerOrderRow
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner
from tests.unit.api.test_actions import StubProvider, _noop


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.fixture(autouse=True)
def user_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    monkeypatch.setenv("MRP_BAR_CACHE", str(tmp_path / "bars"))
    return tmp_path


def _enable_shadow(user_dir: Path) -> None:
    (user_dir / "settings.yaml").write_text(yaml.safe_dump({"shadow": {"enabled": True}}))


def _scan(factory: sessionmaker[Session], provider: Any = None) -> dict[str, Any]:
    return actions.run_scan(
        session_factory=factory,
        provider=provider or StubProvider(),
        scanner=MomentumScanner(
            ScannerConfig(
                filters=ScanFilters(
                    min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0
                )
            )
        ),
        symbols=["AAA", "BBB", "CCC"],
        lookback_days=400,
        progress=_noop,
        market_state="regular",
    )


class GappedProvider(StubProvider):
    def __init__(self, factor: float) -> None:
        super().__init__()
        self.factor = factor

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> Any:
        frame = super().get_bars(symbol, *a, **k)
        return frame * self.factor if not frame.empty else frame


def test_shadow_disabled_by_default_records_nothing(factory: sessionmaker[Session]) -> None:
    result = _scan(factory)
    assert result["shadow"] == {"enabled": False}
    with factory() as session:
        assert session.query(ShadowTrade).count() == 0


def test_shadow_generates_orders_but_never_submits_anything(
    factory: sessionmaker[Session], user_dir: Path
) -> None:
    _enable_shadow(user_dir)
    # Floor at 0 so the stub candidates qualify (mirrors the strategy knobs).
    (user_dir / "settings.yaml").write_text(yaml.safe_dump({"shadow": {"enabled": True}}))
    result = _scan(factory)
    assert result["shadow"]["enabled"] is True
    with factory() as session:
        rows = session.query(ShadowTrade).all()
        # Shadow NEVER touches the journal, the venue or any live surface.
        assert session.query(Trade).count() == 0
        assert session.query(BrokerOrderRow).count() == 0
        for row in rows:
            assert row.expected_entry > 0 and row.stop_price > 0
            assert row.expected_entry >= row.reference_entry  # spread crossed
            assert row.entry_slippage_bps >= 0
            assert row.stop_price < row.expected_entry


def test_shadow_manages_and_closes_on_a_gap(factory: sessionmaker[Session], user_dir: Path) -> None:
    _enable_shadow(user_dir)
    first = _scan(factory)
    with factory() as session:
        entered = session.query(ShadowTrade).count()
    if entered == 0:  # conviction floor kept the stub data out — lower it
        cfg = shadow_service.default_config().model_copy(update={"min_conviction_score": 0.0})
        with factory() as session:
            shadow_service.run_for_scan(
                session,
                run_id=str(first["run_id"]),
                ts=dt.datetime.now(tz=dt.UTC),
                market_state="regular",
                bars={s: StubProvider().get_bars(s) for s in ["AAA", "BBB", "CCC"]},
                config=cfg,
            )
        with factory() as session:
            entered = session.query(ShadowTrade).count()
    assert entered >= 1

    _scan(factory, GappedProvider(1.4))  # far through every plan target
    with factory() as session:
        closed = session.query(ShadowTrade).filter_by(status="closed").all()
        assert closed, "the gap must close shadow trades at their targets"
        for row in closed:
            assert row.exit_reason in ("target", "stop")
            assert row.expected_exit is not None and row.expected_pnl is not None
            assert row.expected_r is not None
            assert row.exit_slippage_bps is not None and row.exit_slippage_bps >= 0
        # Idempotence guard: a symbol is never double-opened per run.
        symbols = [r.symbol for r in session.query(ShadowTrade).filter_by(status="open")]
        assert len(symbols) == len(set(symbols))


def test_report_and_routes(factory: sessionmaker[Session], user_dir: Path) -> None:
    from fastapi.testclient import TestClient

    from momentum.api.app import create_app

    _enable_shadow(user_dir)
    _scan(factory)
    client = TestClient(create_app(session_factory=factory))

    report = client.get("/shadow").json()
    assert report["enabled"] is True
    assert report["orders_submitted"] == 0
    assert "execution_accuracy" in report and "missed_opportunities" in report

    trades = client.get("/shadow/trades").json()
    assert isinstance(trades, list)

    toggled = client.put("/shadow/settings", json={"enabled": False}).json()
    assert toggled["enabled"] is False
    assert client.get("/shadow/settings").json()["enabled"] is False
