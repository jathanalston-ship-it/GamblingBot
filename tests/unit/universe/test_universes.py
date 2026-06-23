"""Tests for the universe registry (built-in definitions + resolution + parsing)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from momentum.universe import universes
from momentum.universe.universes import (
    BUILTIN_DEFS,
    DEFAULT_UNIVERSE_KEY,
    UniverseKind,
    builtin_symbols,
    is_builtin,
    known_sectors,
    parse_symbols,
    resolve_builtin,
)

ROOT = Path(__file__).resolve().parents[3]


def test_all_required_builtins_present() -> None:
    keys = {d.key for d in BUILTIN_DEFS}
    assert {"default", "sp500", "nasdaq100", "russell1000", "russell3000", "all"} <= keys


def test_builtin_sizes_are_reasonable() -> None:
    assert len(builtin_symbols("nasdaq100")) == 100
    assert len(builtin_symbols("sp500")) >= 120
    assert len(builtin_symbols("default")) >= 90
    # The broad sets are supersets of the S&P seed.
    assert len(builtin_symbols("russell3000")) >= len(builtin_symbols("sp500"))


def test_resolve_builtin_returns_symbols_and_sectors() -> None:
    u = resolve_builtin("sp500")
    assert u.kind is UniverseKind.BUILTIN
    assert u.size == len(u.symbols)
    assert u.symbols == tuple(s.upper() for s in u.symbols)
    assert len(set(u.symbols)) == len(u.symbols)  # de-duplicated
    # Known symbols carry a sector.
    assert u.sectors.get("AAPL") == "Information Technology"


def test_default_universe_resolves_from_membership() -> None:
    u = resolve_builtin(DEFAULT_UNIVERSE_KEY)
    assert u.size >= 90
    assert is_builtin(DEFAULT_UNIVERSE_KEY)


def test_known_sectors_cover_the_gics_groups() -> None:
    sectors = known_sectors()
    assert "Information Technology" in sectors
    assert "Energy" in sectors
    assert len(sectors) >= 8


def test_parse_symbols_handles_messy_input() -> None:
    parsed = parse_symbols("aapl, msft\nNVDA;googl  aapl")
    assert parsed == ["AAPL", "MSFT", "NVDA", "GOOGL"]  # upper, dedupe, multi-delimiter


def test_parse_symbols_drops_invalid_tokens() -> None:
    assert parse_symbols("AAPL 123 !!! brk-b") == ["AAPL", "BRK-B"]
    assert parse_symbols("") == []


def test_shipped_yaml_matches_embedded_default() -> None:
    """The shipped universes config must not drift from the in-code default."""
    raw = (ROOT / "config" / "universes.example.yaml").read_text()
    data: dict[str, Any] = yaml.safe_load(raw)
    assert data == universes._EMBEDDED_UNIVERSES
