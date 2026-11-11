"""The home-screen aggregate + the strategy service (market gate, equity, rules)."""

from __future__ import annotations

import datetime as dt
import zlib
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, strategy_service, today_service
from momentum.api import trade_lifecycle_service as svc
from momentum.api.app import create_app
from momentum.persistence.models import Base
from momentum.persistence.models.market_regime import MarketRegime
from momentum.strategy import StrategyConfig
from momentum.universe.screener import MomentumScanner

SYMBOLS = [f"SYM{i:03d}" for i in range(10)]
NOW = dt.datetime.now(tz=dt.UTC)


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


class Provider:
    """Deterministic rising names; SPY's trend is switchable (the market gate)."""

    name = "stub"

    def __init__(self, *, spy_drift: float = 0.0006) -> None:
        self.spy_drift = spy_drift

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        n = 320
        idx = pd.date_range(end=pd.Timestamp(dt.date.today(), tz="UTC"), periods=n, freq="B")
        if symbol == "SPY":
            close = 400.0 * (1 + self.spy_drift) ** np.arange(n)
        else:
            rng = np.random.default_rng(zlib.crc32(symbol.encode()) % 9999)
            close = 50.0 * np.cumprod(1 + rng.normal(0.004, 0.012, n))
        opens = np.concatenate([[close[0]], close[:-1]])
        return pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(opens, close) * 1.004,
                "low": np.minimum(opens, close) * 0.996,
                "close": close,
                "volume": np.full(n, 3_000_000.0),
            },
            index=idx,
        )


def _scan(factory: sessionmaker[Session], provider: Provider) -> dict[str, Any]:
    return actions.run_scan(
        session_factory=factory,
        provider=provider,
        scanner=MomentumScanner(),
        symbols=SYMBOLS,
        sectors={s: "Technology" for s in SYMBOLS},
        lookback_days=460,
        progress=lambda p, m: None,
        provider_name="stub",
        universe_label="Test",
        market_state="regular",
    )


def test_before_any_scan_the_home_screen_says_so(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        out = today_service.today(s)
    assert "No scan yet" in out["headline"]
    assert out["market"]["uptrend"] is None and out["market"]["entries_allowed"] is False
    assert out["signals"] == [] and out["positions"] == [] and out["evidence"] is None
    assert out["account"]["equity"] == 100_000.0
    assert len(out["rules"]["rules"]) == 4


def test_signals_carry_a_complete_plan_and_the_gate_is_open(
    factory: sessionmaker[Session],
) -> None:
    result = _scan(factory, Provider())
    assert result["candidates"] >= 1
    with factory() as s:
        out = today_service.today(s)
        gate = strategy_service.market_gate(s)
    assert gate.uptrend is True and gate.close is not None and gate.average is not None
    assert gate.close > gate.average and "uptrend" in gate.headline
    assert out["market"]["entries_allowed"] is True
    assert f"{result['candidates']} buy signal" in out["headline"]
    assert len(out["signals"]) == result["candidates"]
    strategy = StrategyConfig()
    for sig in out["signals"]:
        assert sig["entry"] > sig["stop"] > 0 and sig["shares"] > 0
        assert sig["exit_level"] is not None and sig["exit_level"] < sig["entry"]
        assert sig["bars_since_breakout"] < strategy.breakout_within
        # the strategy's sizing: at most 0.5% of the account at risk, 8% per position
        assert sig["risk_dollars"] <= strategy.risk_per_trade_pct * 100_000.0 + 0.01
        assert sig["position_value"] <= strategy.max_position_pct * 100_000.0 + 0.01
        assert sig["held"] is False and "50-day high" in sig["why"]
    assert [s["rank"] for s in out["signals"]] == sorted(s["rank"] for s in out["signals"])


def test_a_taken_trade_becomes_a_position_with_its_exit_levels(
    factory: sessionmaker[Session],
) -> None:
    provider = Provider()
    _scan(factory, provider)
    with factory() as s:
        first = today_service.today(s)["signals"][0]
        take = svc.take_trade(s, first["symbol"], ts=NOW)
        assert take["ok"] is True, take
    _scan(factory, provider)  # the next cycle marks + manages the position
    with factory() as s:
        out = today_service.today(s)
        equity = strategy_service.account_equity(s)
    assert [p["symbol"] for p in out["positions"]] == [first["symbol"]]
    pos = out["positions"][0]
    assert pos["shares"] == first["shares"] and pos["stop"] == pytest.approx(first["stop"])
    assert pos["exit_level"] is not None
    assert pos["sell_below"] == max(pos["stop"], pos["exit_level"])
    assert pos["risk_dollars"] >= 0 and pos["mode"] == "managed"
    assert out["account"]["open_positions"] == 1
    assert out["account"]["slots_free"] == out["account"]["max_positions"] - 1
    assert equity == pytest.approx(100_000.0 + pos["pnl"], abs=0.5)
    held = next(s for s in out["signals"] if s["symbol"] == first["symbol"])
    assert held["held"] is True  # still a signal, flagged as already owned


def test_downtrend_closes_the_gate_and_autopilot_stands_aside(
    factory: sessionmaker[Session], monkeypatch: Any
) -> None:
    from momentum.api import autopilot_service, user_settings

    _scan(factory, Provider(spy_drift=-0.0006))
    with factory() as s:
        out = today_service.today(s)
        gate = strategy_service.market_gate(s)
        assert gate.uptrend is False and gate.entries_allowed is False
        assert "downtrend" in out["headline"]
        assert out["signals"], "signals are still listed — they are just not bought"

        monkeypatch.setattr(
            user_settings,
            "read_autopilot",
            lambda: {**user_settings.DEFAULT_AUTOPILOT, "enabled": True},
        )
        run_id = out["data"]["run_id"]
        result = autopilot_service.run_for_scan(s, run_id=run_id, ts=NOW, market_state="regular")
    assert result["entered"] == 0 and "downtrend" in result["skipped_reason"]


def test_autopilot_buys_the_strongest_signals_first_when_the_gate_is_open(
    factory: sessionmaker[Session], monkeypatch: Any
) -> None:
    from momentum.api import autopilot_service, user_settings

    _scan(factory, Provider())
    monkeypatch.setattr(
        user_settings,
        "read_autopilot",
        lambda: {**user_settings.DEFAULT_AUTOPILOT, "enabled": True, "max_entries_per_cycle": 2},
    )
    with factory() as s:
        signals = today_service.today(s)["signals"]
        run_id = today_service.today(s)["data"]["run_id"]
        result = autopilot_service.run_for_scan(s, run_id=run_id, ts=NOW, market_state="regular")
    expected = [sig["symbol"] for sig in signals][:2]
    assert result["entered"] == len(expected)
    assert [o["symbol"] for o in result["outcomes"] if o["ok"]] == expected


def test_gate_falls_back_to_the_regime_row_for_older_databases(
    factory: sessionmaker[Session],
) -> None:
    with factory() as s:
        s.add(
            MarketRegime(
                as_of=dt.date(2026, 1, 5),
                benchmark_symbol="SPY",
                model_version="v1",
                regime="bullish",
                score=0.5,
                benchmark_close=410.0,
                ma_slow=400.0,
                details={"trend": {"score": 1.0}},  # no market_gate key (pre-upgrade row)
            )
        )
        s.commit()
        gate = strategy_service.market_gate(s)
    assert gate.uptrend is True and gate.close == 410.0 and gate.average == 400.0


def test_evidence_reports_the_latest_backtest_of_the_live_rules(
    factory: sessionmaker[Session],
) -> None:
    actions.run_backtest(
        provider=Provider(),
        symbols=SYMBOLS,
        lookback_days=460,
        progress=lambda p, m: None,
        session_factory=factory,
    )
    with factory() as s:
        ev = today_service.evidence(s)
    assert ev is not None and ev["matches_live_rules"] is True
    assert ev["symbols"] == len(SYMBOLS) and "cagr" in ev and "benchmark_cagr" in ev


def test_today_and_strategy_endpoints(factory: sessionmaker[Session]) -> None:
    _scan(factory, Provider())
    client = TestClient(create_app(session_factory=factory))
    body = client.get("/today").json()
    assert body["signals"] and body["market"]["entries_allowed"] is True
    strategy = client.get("/strategy").json()
    assert strategy["model_version"] == "v2" and strategy["market"]["uptrend"] is True
    assert [r["title"] for r in strategy["rules"]][0] == "Only buy in a rising market"
    with factory() as s:
        assert s.scalars(select(MarketRegime)).first() is not None
