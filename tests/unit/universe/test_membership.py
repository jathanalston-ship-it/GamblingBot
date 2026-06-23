"""Tests for universe selection (the configured tradeable symbol set)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from momentum.universe import membership
from momentum.universe.membership import _EMBEDDED_UNIVERSE, select_universe

ROOT = Path(__file__).resolve().parents[3]


def test_select_universe_returns_symbols_and_sectors() -> None:
    symbols, sectors = select_universe()
    assert len(symbols) >= 90  # a broad cross-section, not a demo handful
    assert symbols == [s.upper() for s in symbols]
    assert len(set(symbols)) == len(symbols)  # de-duplicated
    # Every symbol has a sector, drawn from multiple GICS sectors.
    assert all(s in sectors for s in symbols)
    assert len(set(sectors.values())) >= 8


def test_no_hardcoded_demo_handful() -> None:
    symbols, _ = select_universe()
    # The old hardcoded list was 8 mega-caps; the real universe is far larger.
    assert len(symbols) > 50


def test_shipped_yaml_matches_embedded_default() -> None:
    """The shipped example config must not drift from the in-code default."""
    raw = (ROOT / "config" / "universe_symbols.example.yaml").read_text()
    data: dict[str, Any] = yaml.safe_load(raw)
    assert data == _EMBEDDED_UNIVERSE


def test_user_override_is_respected(tmp_path: Path, monkeypatch: Any) -> None:
    """A user-provided universe config overrides the embedded default."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    # The user-override filename drops the ".example" segment.
    (cfg_dir / membership.UNIVERSE_FILE.replace(".example", "")).write_text(
        yaml.safe_dump(
            {"members": [{"symbol": "zzz", "sector": "Test"}, {"symbol": "zzz", "sector": "Dup"}]}
        )
    )
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    symbols, sectors = select_universe()
    assert symbols == ["ZZZ"]  # upper-cased + de-duplicated
    assert sectors == {"ZZZ": "Test"}
