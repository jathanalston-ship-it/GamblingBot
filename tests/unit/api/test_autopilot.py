"""Autopilot tests: opt-in auto-entries through the real take-trade path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, user_settings
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Alert, Base, Trade
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


@pytest.fixture
def user_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    return tmp_path


def _configure(user_dir: Path, **autopilot: Any) -> None:
    """Persist autopilot settings the way the app does (current rules generation)."""
    from momentum.api.user_settings import AUTOPILOT_RULES_VERSION

    autopilot.setdefault("rules_version", AUTOPILOT_RULES_VERSION)
    (user_dir / "settings.yaml").write_text(yaml.safe_dump({"autopilot": autopilot}))


def test_limits_saved_under_the_old_rules_are_not_carried_over(user_dir: Path) -> None:
    """Before the strategy change any toggle persisted that era's defaults
    (8 positions, conviction >= 70). They must not silently restrict the new
    rules; the on/off switches themselves are always honoured."""
    from momentum.api import user_settings

    legacy = {
        "enabled": True,
        "include_premarket": True,
        "max_open_positions": 8,
        "max_entries_per_cycle": 2,
        "min_conviction_score": 70.0,
    }
    (user_dir / "settings.yaml").write_text(yaml.safe_dump({"autopilot": legacy}))
    loaded = user_settings.read_autopilot()
    assert loaded["enabled"] is True and loaded["include_premarket"] is True
    assert loaded["max_open_positions"] == user_settings.DEFAULT_AUTOPILOT["max_open_positions"]
    assert loaded["min_conviction_score"] == 0.0

    # Saving from the UI stamps the current generation; those values then stick.
    user_settings.write_autopilot(max_open_positions=12, min_conviction_score=55.0)
    again = user_settings.read_autopilot()
    assert again["max_open_positions"] == 12 and again["min_conviction_score"] == 55.0


def _relaxed() -> MomentumScanner:
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        ),
        strategy_gates=False,
    )


def _scan(factory: sessionmaker[Session], *, market_state: str = "regular") -> dict[str, Any]:
    return actions.run_scan(
        session_factory=factory,
        provider=StubProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB", "CCC"],
        lookback_days=400,
        progress=_noop,
        market_state=market_state,
    )


def test_autopilot_off_by_default(factory: sessionmaker[Session], user_dir: Path) -> None:
    result = _scan(factory)
    assert result["autopilot_enabled"] is False
    assert result["autopilot_entries"] == 0
    with factory() as session:
        assert session.query(Trade).filter_by(status="open").count() == 0


def test_autopilot_takes_committee_reviewed_entries(
    factory: sessionmaker[Session], user_dir: Path
) -> None:
    _configure(user_dir, enabled=True, min_conviction_score=0, max_entries_per_cycle=2)
    result = _scan(factory)
    assert result["autopilot_enabled"] is True
    assert 1 <= result["autopilot_entries"] <= 2
    with factory() as session:
        open_trades = session.query(Trade).filter_by(status="open").all()
        assert len(open_trades) == result["autopilot_entries"]
        # Every auto-entry has a stop and a size — it went through the plan.
        assert all(t.initial_stop is not None and t.quantity > 0 for t in open_trades)
        # ... and announced itself (Command Center + OS-notification hook).
        alerts = session.query(Alert).filter_by(kind="autopilot_entry").all()
        assert len(alerts) == result["autopilot_entries"]
        # ... and passed a persisted committee review on the way in.
        from momentum.persistence.models.committee_meeting import CommitteeMeeting

        assert session.query(CommitteeMeeting).filter_by(context="entry").count() >= len(
            open_trades
        )


def test_autopilot_respects_entry_cap(factory: sessionmaker[Session], user_dir: Path) -> None:
    _configure(user_dir, enabled=True, min_conviction_score=0, max_entries_per_cycle=1)
    result = _scan(factory)
    assert result["autopilot_entries"] <= 1


def test_autopilot_waits_for_the_open_by_default(
    factory: sessionmaker[Session], user_dir: Path
) -> None:
    _configure(user_dir, enabled=True, min_conviction_score=0)
    premarket = _scan(factory, market_state="premarket")
    assert premarket["autopilot_entries"] == 0  # scans + manages, entries wait


def test_autopilot_premarket_opt_in(factory: sessionmaker[Session], user_dir: Path) -> None:
    _configure(user_dir, enabled=True, min_conviction_score=0, include_premarket=True)
    result = _scan(factory, market_state="premarket")
    assert result["autopilot_entries"] >= 1


def test_autopilot_rerun_is_idempotent(factory: sessionmaker[Session], user_dir: Path) -> None:
    """A second cycle never re-enters symbols already held."""
    _configure(user_dir, enabled=True, min_conviction_score=0, max_entries_per_cycle=5)
    first = _scan(factory)
    second = _scan(factory)
    with factory() as session:
        symbols = [t.symbol for t in session.query(Trade).filter_by(status="open").all()]
    assert len(symbols) == len(set(symbols))  # no duplicate positions
    assert first["autopilot_entries"] >= 1
    assert second["autopilot_entries"] == 0  # everything eligible is already held


def test_account_balance_settings_round_trip(user_dir: Path) -> None:
    assert user_settings.read_account_balance() == 100_000.0
    user_settings.write_account_balance(25_000.0)
    assert user_settings.read_account_balance() == 25_000.0
    with pytest.raises(ValueError):
        user_settings.write_account_balance(0)


def test_autopilot_settings_round_trip(user_dir: Path) -> None:
    prefs = user_settings.write_autopilot(enabled=True, max_entries_per_cycle=3)
    assert prefs["enabled"] is True
    assert prefs["max_entries_per_cycle"] == 3
    assert user_settings.read_autopilot()["enabled"] is True
    with pytest.raises(ValueError):
        user_settings.write_autopilot(min_conviction_score=150)
