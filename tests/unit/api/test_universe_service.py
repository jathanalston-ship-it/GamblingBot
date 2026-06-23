"""Tests for the universe-management service (list/create/import/sector/select)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import universe_service as us
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base, UserUniverse


@pytest.fixture(autouse=True)
def _isolated_user_dir(tmp_path: Path, monkeypatch: Any) -> None:
    """Persist the selection to a tmp settings.yaml, never the repo."""
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def test_list_includes_builtins_and_default_selection(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        out = us.list_universes(s)
    keys = {u["key"] for u in out["universes"]}
    assert {"default", "sp500", "nasdaq100", "russell1000", "russell3000", "all"} <= keys
    assert out["selected"] == "default"
    assert all(u["size"] > 0 for u in out["universes"])
    assert out["sectors"]


def test_create_custom_persists_and_appears(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        created = us.create_custom(s, label="My Picks", symbols=["aapl", "msft", "aapl"])
        assert created["kind"] == "custom"
        assert created["size"] == 2  # de-duplicated
    with factory() as s:
        row = s.query(UserUniverse).filter_by(key=created["key"]).one()
        assert row.symbols == ["AAPL", "MSFT"]
        listing = us.list_universes(s)
    assert any(u["key"] == created["key"] and u["editable"] for u in listing["universes"])


def test_create_custom_rejects_empty(factory: sessionmaker[Session]) -> None:
    with factory() as s, pytest.raises(us.UniverseError):
        us.create_custom(s, label="empty", symbols=["!!!", "123"])


def test_import_parses_freeform_list(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        out = us.import_symbols(s, label="Imported", text="NVDA, TSLA\nGOOGL; AMZN")
    assert out["kind"] == "imported"
    assert set(out["symbols"]) == {"NVDA", "TSLA", "GOOGL", "AMZN"}


def test_sector_universe_filters_base(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        out = us.create_sector(s, sector="Energy", base_key="default")
        assert out["kind"] == "sector"
        assert out["size"] >= 1
        resolved = us.resolve(s, out["key"])
    assert all(resolved.sectors.get(sym) == "Energy" for sym in resolved.symbols)


def test_select_and_resolve_selected(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        us.set_selected(s, "nasdaq100")
        resolved = us.resolve_selected(s)
    assert resolved.key == "nasdaq100"
    assert resolved.size == 100


def test_select_unknown_raises(factory: sessionmaker[Session]) -> None:
    with factory() as s, pytest.raises(us.UniverseError):
        us.set_selected(s, "does-not-exist")


def test_delete_user_universe_resets_selection(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        created = us.create_custom(s, label="Temp", symbols=["AAPL"])
        us.set_selected(s, created["key"])
    with factory() as s:
        assert us.delete_universe(s, created["key"]) is True
        # The selection fell back to the default after its universe was deleted.
        assert us.resolve_selected(s).key == "default"


def test_cannot_delete_builtin(factory: sessionmaker[Session]) -> None:
    with factory() as s, pytest.raises(us.UniverseError):
        us.delete_universe(s, "sp500")
