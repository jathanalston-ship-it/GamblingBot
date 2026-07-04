"""Command Center backend: HUD aggregate, bot status, search, verdicts.

Every UI element must be backed by real backend data — these tests run the
real scan pipeline (stub provider) and then verify each aggregate derives
from the rows it produced, never fabricating a number.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, autopilot_service, hud_service, verdict_service
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner
from tests.unit.api.test_actions import StubProvider, _noop

NOW = dt.datetime(2026, 7, 1, 15, 0, tzinfo=dt.UTC)


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


def _scan(factory: sessionmaker[Session]) -> dict[str, Any]:
    return actions.run_scan(
        session_factory=factory,
        provider=StubProvider(),
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


class FakeDaemon:
    def __init__(self, **overrides: Any) -> None:
        self.payload: dict[str, Any] = {
            "running": True,
            "paused": False,
            "scanning_now": False,
            "market_state": "regular",
            "cycles": 7,
            "seconds_to_next_wake": 42.0,
            "next_wake_at": NOW.isoformat(),
            "last_scan_at": NOW.isoformat(),
            "last_result": {"autopilot_entries": 1, "trades_reevaluated": 3, "candidates": 5},
            "last_error": None,
        }
        self.payload.update(overrides)

    def status(self) -> dict[str, Any]:
        return dict(self.payload)


def test_hud_derives_every_block_from_live_rows(factory: sessionmaker[Session]) -> None:
    scan = _scan(factory)
    with factory() as session:
        hud = hud_service.hud(session, daemon=FakeDaemon())

    assert hud["clock"]["state"] in ("premarket", "regular", "after_hours", "closed")
    for light in ("backend", "scheduler", "automation", "broker", "data_provider"):
        assert hud["health"][light]["status"] in ("green", "yellow", "red")
        assert hud["health"][light]["detail"]
    assert hud["health"]["scheduler"]["status"] == "green"

    # Timestamps trace to the scan we just ran.
    assert hud["timestamps"]["latest_scan"] is not None
    assert scan["run_id"]

    account = hud["account"]
    assert account["starting_balance"] == 100_000.0
    assert account["equity"] == pytest.approx(100_000.0)  # nothing taken yet
    assert account["open_positions"] == 0
    assert account["heat_cap_pct"] == pytest.approx(5.0)  # the real risk config

    market = hud["market"]
    assert market["regime"] in ("bullish", "neutral", "bearish")  # persisted by the scan
    assert market["breadth_pct"] is None or 0 <= market["breadth_pct"] <= 100


def test_hud_account_reflects_an_open_position(factory: sessionmaker[Session]) -> None:
    from momentum.api import trade_lifecycle_service

    _scan(factory)
    with factory() as session:
        take = trade_lifecycle_service.take_trade(session, "AAA", ts=dt.datetime.now(tz=dt.UTC))
        assert take["ok"], take.get("error")
    with factory() as session:
        account = hud_service.hud(session, daemon=None)["account"]
    assert account["open_positions"] == 1
    assert account["exposure"] > 0
    assert account["risk_used"] > 0
    assert account["cash"] < 100_000.0  # shares paid for out of cash
    assert account["max_risk_allowed"] == pytest.approx(0.05 * account["equity"], rel=1e-6)


def test_autopilot_status_states(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    with factory() as session:
        stopped = autopilot_service.status(session, daemon=FakeDaemon(running=False))
        assert stopped["state"] == "stopped"

        paused = autopilot_service.status(session, daemon=FakeDaemon(paused=True))
        assert paused["state"] == "paused"

        scanning = autopilot_service.status(session, daemon=FakeDaemon(scanning_now=True))
        assert scanning["state"] == "scanning"
        assert "Scanning" in scanning["activity"]

        waiting = autopilot_service.status(session, daemon=FakeDaemon(market_state="closed"))
        assert waiting["state"] == "waiting"
        assert "Waiting" in waiting["activity"]

        idle = autopilot_service.status(session, daemon=FakeDaemon())
        assert idle["state"] == "idle"  # autopilot off by default
        assert "Auto Pilot is OFF" in idle["activity"]
        assert idle["next_action"]["seconds"] == 42.0
        assert idle["last_cycle"]["entered"] == 1


def test_autopilot_status_entering_and_exiting_from_scan_phase(
    factory: sessionmaker[Session],
) -> None:
    """During a scan, the live pipeline phase refines SCANNING into
    ENTERING (autopilot entries) / EXITING (managing open trades)."""
    _scan(factory)
    with factory() as session:
        entering = autopilot_service.status(
            session,
            daemon=FakeDaemon(scanning_now=True, scan_phase="autopilot — evaluating entries"),
        )
        assert entering["state"] == "entering"
        assert entering["state_label"] == "ENTERING"
        assert "entries" in entering["activity"].lower()

        exiting = autopilot_service.status(
            session,
            daemon=FakeDaemon(scanning_now=True, scan_phase="reevaluating + managing open trades"),
        )
        assert exiting["state"] == "exiting"
        assert exiting["state_label"] == "EXITING"
        assert "stops" in exiting["activity"].lower()

        early = autopilot_service.status(
            session, daemon=FakeDaemon(scanning_now=True, scan_phase="pulling market data")
        )
        assert early["state"] == "scanning"  # unknown/early phases stay SCANNING


def test_conviction_trend_between_evaluations(factory: sessionmaker[Session]) -> None:
    from momentum.api import trade_lifecycle_service
    from momentum.api.trade_lifecycle_service import _conviction_trend
    from momentum.persistence.models.trade_evaluation import TradeEvaluation

    up = TradeEvaluation(trade_uid="u", symbol="AAA", current_conviction=70.0)
    down = TradeEvaluation(trade_uid="u", symbol="AAA", current_conviction=64.0)
    assert _conviction_trend(up, down) == {"conviction_trend": "rising", "conviction_change": 6.0}
    assert _conviction_trend(down, up)["conviction_trend"] == "falling"
    assert _conviction_trend(up, up)["conviction_trend"] == "flat"
    assert _conviction_trend(up, None)["conviction_trend"] is None  # one eval = no trend

    # End to end: take a position, run further scans (fresh evaluations), and
    # the mark carries a measured trend — never invented.
    _scan(factory)
    with factory() as session:
        take = trade_lifecycle_service.take_trade(session, "AAA", ts=dt.datetime.now(tz=dt.UTC))
        assert take["ok"], take.get("error")
    _scan(factory)
    _scan(factory)
    with factory() as session:
        trade = next(
            t
            for t in trade_lifecycle_service.list_trades(session, status="open")
            if t.symbol == "AAA"
        )
    assert trade.conviction_trend in ("rising", "falling", "flat")


def test_autopilot_status_managing_when_positions_open(
    factory: sessionmaker[Session], user_dir: Path
) -> None:
    import yaml

    from momentum.api import trade_lifecycle_service

    (user_dir / "settings.yaml").write_text(yaml.safe_dump({"autopilot": {"enabled": True}}))
    _scan(factory)
    with factory() as session:
        take = trade_lifecycle_service.take_trade(session, "AAA", ts=dt.datetime.now(tz=dt.UTC))
        # Autopilot (enabled) may have already entered AAA during the scan.
        assert take["ok"] or "already has an open paper trade" in str(take.get("error"))
    with factory() as session:
        status = autopilot_service.status(session, daemon=FakeDaemon())
    assert status["state"] == "managing"
    # Autopilot (enabled) may have entered candidates during the scan too.
    assert "Managing" in status["activity"]
    assert status["managed_positions"] >= 1


def test_search_returns_scanned_symbols_with_context(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    with factory() as session:
        hits = hud_service.search_symbols(session, "a")
    assert hits and hits[0]["symbol"] == "AAA"
    assert hits[0]["price"] > 0 and hits[0]["source"] == "scan"
    with factory() as session:
        assert hud_service.search_symbols(session, "") == []


def test_verdict_is_complete_and_never_a_bare_no(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    with factory() as session:
        verdict = verdict_service.verdict_for(session, "AAA")
    assert verdict is not None
    payload = verdict.to_dict()
    assert payload["verdict"] in ("BUY", "WATCH", "WAIT", "AVOID")
    assert payload["reasons"], "every verdict must carry named reasons"
    assert payload["next_condition"], "never a bare no — always the next condition"
    explainer = payload["explainer"]
    for key in (
        "why_this_trade",
        "why_now",
        "why_not_yesterday",
        "what_would_invalidate",
        "what_would_improve",
        "what_would_reduce_conviction",
        "why_this_stop",
        "why_this_target",
        "why_this_size",
        "instrument",
    ):
        assert key in explainer

    with factory() as session:
        assert verdict_service.verdict_for(session, "ZZZZ") is None  # never invented


def test_hud_endpoint_over_http(factory: sessionmaker[Session]) -> None:
    from fastapi.testclient import TestClient

    from momentum.api.app import create_app

    _scan(factory)
    client = TestClient(create_app(session_factory=factory))
    hud = client.get("/command-center/hud").json()
    assert set(hud) >= {"clock", "health", "timestamps", "account", "market", "generated_at"}
    bot = client.get("/command-center/autopilot").json()
    assert bot["state_label"] in (
        "RUNNING",
        "PAUSED",
        "STOPPED",
        "WAITING",
        "SCANNING",
        "ENTERING",
        "EXITING",
        "MANAGING",
        "IDLE",
    )
    hits = client.get("/command-center/search", params={"q": "AA"}).json()
    assert hits and hits[0]["symbol"] == "AAA"
    verdict = client.get("/tradeplan/AAA/verdict").json()
    assert verdict["verdict"] in ("BUY", "WATCH", "WAIT", "AVOID")
    assert client.get("/tradeplan/ZZZZ/verdict").status_code == 404
