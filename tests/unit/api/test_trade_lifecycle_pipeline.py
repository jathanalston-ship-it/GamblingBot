"""Trade lifecycle pipeline — every scan creates tracked trades from its
recommendations and reevaluates every OPEN trade, appending (never overwriting)
evaluation history; the /trade-lifecycle routes serve the results."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions
from momentum.persistence.models import Base, TrackedTrade, TradeEvaluation
from momentum.universe.screener import MomentumScanner

SYMBOLS = [f"SYM{i:03d}" for i in range(15)]


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    monkeypatch.setenv("MRP_BAR_CACHE", str(tmp_path / "bars"))


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _bars(seed: int, newest: pd.Timestamp, n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50.0 * np.cumprod(1 + rng.normal(0.004, 0.02, n))
    idx = pd.date_range(end=newest, periods=n, freq="B")
    opens = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.02,
            "low": np.minimum(opens, close) * 0.98,
            "close": close,
            "volume": np.full(n, 3_000_000.0),
        },
        index=idx,
    )


class StubProvider:
    def __init__(self, newest: pd.Timestamp) -> None:
        self.newest = newest

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        return _bars(abs(hash(symbol)) % 9999, self.newest)


def _scan(factory: sessionmaker[Session], days_old: int = 0) -> dict[str, Any]:
    newest = pd.Timestamp(dt.date.today() - dt.timedelta(days=days_old), tz="UTC")
    return actions.run_scan(
        session_factory=factory,
        provider=StubProvider(newest),
        scanner=MomentumScanner(),
        symbols=SYMBOLS,
        sectors={s: "Technology" for s in SYMBOLS},
        lookback_days=400,
        progress=lambda p, m: None,
        provider_name="stub",
        universe_label="Default",
    )


def _counts(factory: sessionmaker[Session]) -> tuple[int, int]:
    with factory() as s:
        trades = int(s.scalar(select(func.count()).select_from(TrackedTrade)) or 0)
        evals = int(s.scalar(select(func.count()).select_from(TradeEvaluation)) or 0)
    return trades, evals


def test_scan_creates_tracked_trades_and_first_evaluations(
    factory: sessionmaker[Session],
) -> None:
    result = _scan(factory)
    assert result["stale"] is False
    assert result["tracked_trades_created"] == result["trade_plans_persisted"] > 0
    assert result["trades_reevaluated"] == result["tracked_trades_created"]

    trades, evals = _counts(factory)
    assert trades == result["tracked_trades_created"]
    assert evals == result["trades_reevaluated"]

    with factory() as s:
        row = s.scalars(select(TrackedTrade).limit(1)).first()
        assert row is not None
        assert row.status == "open"
        assert row.trade_uid
        assert row.recommended_at is not None
        assert row.entry_price > row.stop_price
        assert row.conviction_score is not None  # original thesis evidence captured
        assert row.regime is not None
        assert row.current_thesis_strength is not None  # first evaluation applied
        assert row.trade_health is not None
        assert row.last_evaluated_at is not None


def test_rescans_reevaluate_never_recreate_never_overwrite(
    factory: sessionmaker[Session],
) -> None:
    first = _scan(factory)
    trades_1, evals_1 = _counts(factory)

    second = _scan(factory)
    assert second["tracked_trades_created"] == 0  # idempotent creation
    assert second["trades_reevaluated"] == first["tracked_trades_created"]

    trades_2, evals_2 = _counts(factory)
    assert trades_2 == trades_1  # no duplicates
    assert evals_2 == evals_1 + second["trades_reevaluated"]  # history appended

    with factory() as s:
        uid = s.scalars(select(TrackedTrade.trade_uid).limit(1)).first()
        history = list(s.scalars(select(TradeEvaluation).where(TradeEvaluation.trade_uid == uid)))
    assert len(history) == 2
    # both evaluations retained, each with the full metric set
    for ev in history:
        assert ev.momentum_trend and ev.rs_trend and ev.volume_trend
        assert 0.0 <= ev.thesis_strength <= 100.0
        assert 0.0 <= ev.thesis_stability <= 1.0
        assert ev.action
        assert ev.current_conviction is not None
        assert ev.conviction_delta is not None


def test_stale_scan_tracks_nothing(factory: sessionmaker[Session]) -> None:
    result = _scan(factory, days_old=10)
    assert result["stale"] is True
    assert result["tracked_trades_created"] == 0
    assert result["trades_reevaluated"] == 0
    assert _counts(factory) == (0, 0)


def test_routes_serve_trades_and_history(factory: sessionmaker[Session]) -> None:
    from fastapi.testclient import TestClient

    from momentum.api.app import create_app
    from momentum.api.jobs import JobManager

    _scan(factory)
    _scan(factory)

    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    client = TestClient(app)

    trades = client.get("/trade-lifecycle?status=open").json()
    assert trades
    trade = trades[0]
    assert trade["status"] == "open"
    assert trade["current_thesis_strength"] is not None

    detail = client.get(f"/trade-lifecycle/{trade['trade_uid']}").json()
    assert detail["symbol"] == trade["symbol"]

    history = client.get(f"/trade-lifecycle/{trade['trade_uid']}/evaluations").json()
    assert len(history) == 2
    assert {"thesis_strength", "action", "health", "momentum_trend"} <= set(history[0])

    summary = client.get("/trade-lifecycle/summary").json()
    assert summary["total"] == len(trades)
    assert summary["by_status"].get("open") == len(trades)
    assert sum(summary["by_action"].values()) == len(trades) * 2

    assert client.get("/trade-lifecycle/nope").status_code == 404


def test_stop_breach_auto_closes(factory: sessionmaker[Session]) -> None:
    """A trade whose price later breaches its stop is Exited and closed."""
    import momentum.api.trade_lifecycle_service as svc
    from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository

    _scan(factory)
    with factory() as s:
        row = s.scalars(select(TrackedTrade).limit(1)).first()
        assert row is not None
        symbol, uid = row.symbol, row.trade_uid
        # Force a breach: raise the stored stop far above any price.
        row.stop_price = 1_000_000.0
        s.commit()

    with factory() as s:
        counts = svc.reevaluate_open_trades(session=s, ts=dt.datetime.now(tz=dt.UTC))
        assert counts["closed"] >= 1

    with factory() as s:
        closed = TrackedTradeRepository(s).get_by_uid(uid)
        assert closed is not None
        assert closed.symbol == symbol
        assert closed.status == "closed"
        assert closed.close_reason
        assert closed.closed_at is not None
        # a closed trade is not reevaluated again
        again = svc.reevaluate_open_trades(session=s, ts=dt.datetime.now(tz=dt.UTC))
        assert again["evaluated"] == counts["evaluated"] - counts["closed"]

    with factory() as s:
        history = s.scalars(select(TradeEvaluation).where(TradeEvaluation.trade_uid == uid)).all()
    assert len(history) == 2  # scan eval + breach eval, nothing after close
