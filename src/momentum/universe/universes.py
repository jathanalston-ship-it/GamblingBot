"""Universe management — multiple selectable universes for the scanner.

A *universe* is the set of symbols the scanner fetches and ranks. The platform
supports several kinds:

* **Built-in** — curated, well-known index sets (``SP500``, ``NASDAQ100``,
  ``Russell1000``, ``Russell3000``, ``All Tradable Stocks``) plus the platform
  ``default`` (the config-driven large-cap set in :mod:`momentum.universe.membership`).
  Their member lists are shipped as configuration (``config/universes.example.yaml``)
  with an in-code embedded default, so a packaged build never needs a repo file.
* **Sector** — a built-in (or default) universe filtered to one GICS sector.
* **Custom / Imported** — user-defined symbol lists (created in the UI or imported
  from a pasted/file list), persisted in the ``user_universes`` table.

The big index sets (Russell 1000/3000, All Tradable) ship as **extendable seeds**:
the engine processes a universe of any size (verified to 3000+), and a user can
import the full membership from their own data source. ``resolve`` returns the
symbols + a ``{symbol: sector}`` map for whichever universe is selected; the
scanner is otherwise unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from momentum.core.config_paths import load_config
from momentum.universe.membership import _EMBEDDED_MEMBERS, select_universe

UNIVERSES_FILE = "universes.example.yaml"
DEFAULT_UNIVERSE_KEY = "default"


class UniverseKind(str, Enum):
    """How a universe is sourced."""

    BUILTIN = "builtin"
    SECTOR = "sector"
    CUSTOM = "custom"
    IMPORTED = "imported"


@dataclass(frozen=True, slots=True)
class UniverseDef:
    """A selectable universe's identity (not its members)."""

    key: str
    label: str
    kind: UniverseKind
    description: str


@dataclass(frozen=True, slots=True)
class ResolvedUniverse:
    """A universe's resolved membership."""

    key: str
    label: str
    kind: UniverseKind
    symbols: tuple[str, ...]
    sectors: dict[str, str]

    @property
    def size(self) -> int:
        return len(self.symbols)


def _dedupe(symbols: Iterable[str]) -> list[str]:
    """Upper-case, strip and de-duplicate symbols, preserving first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for s in symbols:
        s = s.strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# --------------------------------------------------------------------------- #
# Built-in universe member lists (embedded default → config-overridable).
# --------------------------------------------------------------------------- #
# A sector map for every embedded symbol, reused across the built-ins.
_SECTOR_OF: dict[str, str] = {sym: sec for sym, sec in _EMBEDDED_MEMBERS}

# NASDAQ-100 (large-cap non-financial Nasdaq names). Accurate, shippable.
_NASDAQ100: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "GOOG",
    "AVGO",
    "TSLA",
    "COST",
    "NFLX",
    "ADBE",
    "PEP",
    "AMD",
    "CSCO",
    "TMUS",
    "INTU",
    "TXN",
    "QCOM",
    "AMGN",
    "INTC",
    "AMAT",
    "ISRG",
    "BKNG",
    "HON",
    "VRTX",
    "ADP",
    "REGN",
    "MU",
    "LRCX",
    "PANW",
    "GILD",
    "ADI",
    "SBUX",
    "MELI",
    "MDLZ",
    "PYPL",
    "KLAC",
    "SNPS",
    "CDNS",
    "MAR",
    "CRWD",
    "ABNB",
    "ORLY",
    "CTAS",
    "ASML",
    "NXPI",
    "PCAR",
    "CEG",
    "ROP",
    "MNST",
    "WDAY",
    "MRVL",
    "FTNT",
    "DASH",
    "ADSK",
    "AEP",
    "PAYX",
    "KDP",
    "ODFL",
    "CHTR",
    "TTD",
    "ROST",
    "FAST",
    "EA",
    "KHC",
    "CSGP",
    "DDOG",
    "EXC",
    "VRSK",
    "CTSH",
    "GEHC",
    "XEL",
    "BKR",
    "CCEP",
    "LULU",
    "IDXX",
    "TEAM",
    "ON",
    "ANSS",
    "ZS",
    "DXCM",
    "CDW",
    "BIIB",
    "MDB",
    "GFS",
    "TTWO",
    "ILMN",
    "WBD",
    "MCHP",
    "ARM",
    "SMCI",
    "PDD",
    "WBA",
    "MRNA",
    "DLTR",
    "SIRI",
    "LCID",
    "ENPH",
    "ALGN",
)

# A broad large/mid-cap S&P-500 seed (the embedded 96 large caps + well-known
# additions across all sectors). A genuine, shippable seed — extend via import
# for the full 500.
_SP500_EXTRA: tuple[str, ...] = (
    "GOOG",
    "COST",
    "NFLX",
    "ADP",
    "PGR",
    "PLD",
    "BSX",
    "SYK",
    "VRTX",
    "REGN",
    "ISRG",
    "CB",
    "MMC",
    "ZTS",
    "BDX",
    "CI",
    "SO",
    "DUK",
    "EQIX",
    "AON",
    "ITW",
    "CME",
    "MO",
    "GD",
    "CL",
    "NOC",
    "FCX",
    "USB",
    "PNC",
    "EW",
    "HUM",
    "TFC",
    "EOG",
    "APH",
    "ADI",
    "KLAC",
    "LRCX",
    "SNPS",
    "CDNS",
    "ORLY",
    "MNST",
    "CTAS",
    "ROP",
    "MSCI",
    "MCO",
    "EMR",
    "NSC",
    "PSX",
    "MPC",
    "VLO",
    "WMB",
    "KMI",
    "OXY",
    "HES",
    "DOW",
    "DD",
    "ECL",
    "NEM",
    "NUE",
    "STLD",
    "PH",
    "ETN",
    "CMI",
    "ROK",
    "AME",
    "FDX",
    "WM",
    "RSG",
    "PCAR",
    "PAYX",
)


def _builtin_symbol_lists() -> dict[str, list[str]]:
    """Embedded default member lists for the built-in universes.

    ``russell1000``/``russell3000``/``all`` ship as extendable seeds (the broad
    S&P-500 seed) — the engine handles any size and the full membership can be
    imported by the user. The size reported everywhere is the *actual* loaded list.
    """
    default_symbols = [s for s, _ in _EMBEDDED_MEMBERS]
    sp500 = _dedupe([*default_symbols, *_SP500_EXTRA])
    nasdaq100 = _dedupe(_NASDAQ100)
    broad = _dedupe([*sp500, *nasdaq100])
    return {
        "sp500": sp500,
        "nasdaq100": nasdaq100,
        "russell1000": broad,
        "russell3000": broad,
        "all": broad,
    }


# JSON-able embedded default (mirrors config/universes.example.yaml).
_EMBEDDED_UNIVERSES: dict[str, Any] = {"universes": _builtin_symbol_lists()}


# Built-in universe definitions, in display order.
BUILTIN_DEFS: tuple[UniverseDef, ...] = (
    UniverseDef(
        DEFAULT_UNIVERSE_KEY,
        "Default (Large-Cap)",
        UniverseKind.BUILTIN,
        "The platform's curated large-cap, highly-liquid US equity set.",
    ),
    UniverseDef("sp500", "S&P 500", UniverseKind.BUILTIN, "Large-cap S&P 500 constituents (seed)."),
    UniverseDef(
        "nasdaq100",
        "NASDAQ 100",
        UniverseKind.BUILTIN,
        "The 100 largest non-financial Nasdaq names.",
    ),
    UniverseDef(
        "russell1000",
        "Russell 1000",
        UniverseKind.BUILTIN,
        "Large/mid-cap US equities (extendable seed — import the full list).",
    ),
    UniverseDef(
        "russell3000",
        "Russell 3000",
        UniverseKind.BUILTIN,
        "Broad US market (extendable seed — import the full list).",
    ),
    UniverseDef(
        "all",
        "All Tradable Stocks",
        UniverseKind.BUILTIN,
        "Every tradable US equity (extendable seed — import from your data source).",
    ),
)

_BUILTIN_KEYS = {d.key for d in BUILTIN_DEFS}


def is_builtin(key: str) -> bool:
    return key in _BUILTIN_KEYS


def builtin_def(key: str) -> UniverseDef | None:
    return next((d for d in BUILTIN_DEFS if d.key == key), None)


# --------------------------------------------------------------------------- #
# Symbol-list parsing (for imported universes).
# --------------------------------------------------------------------------- #
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")


def parse_symbols(raw: str) -> list[str]:
    """Parse a free-form symbol list (comma / whitespace / newline separated).

    Upper-cases, validates each token against a ticker shape, and de-duplicates
    while preserving order. Invalid tokens are dropped silently so a pasted list
    with headers/notes still imports cleanly.
    """
    tokens = re.split(r"[\s,;]+", raw.strip().upper())
    return _dedupe(t for t in tokens if _SYMBOL_RE.match(t))


# --------------------------------------------------------------------------- #
# Built-in resolution.
# --------------------------------------------------------------------------- #
def builtin_symbols(key: str) -> list[str]:
    """The member symbols for a built-in universe (config → embedded default)."""
    if key == DEFAULT_UNIVERSE_KEY:
        return select_universe()[0]
    data = load_config(UNIVERSES_FILE, embedded=_EMBEDDED_UNIVERSES)
    section = data.get("universes") if isinstance(data, dict) else None
    members = section.get(key) if isinstance(section, dict) else None
    if not isinstance(members, list):
        members = _builtin_symbol_lists().get(key, [])
    return _dedupe(str(s) for s in members)


def sectors_for(symbols: Iterable[str]) -> dict[str, str]:
    """Best-effort ``{symbol: sector}`` map for known symbols."""
    return {s: _SECTOR_OF[s] for s in symbols if s in _SECTOR_OF}


def known_sectors() -> list[str]:
    """The distinct GICS sectors available for sector universes."""
    return sorted(set(_SECTOR_OF.values()))


def resolve_builtin(key: str) -> ResolvedUniverse:
    """Resolve a built-in universe by key (raises ``KeyError`` if unknown)."""
    definition = builtin_def(key)
    if definition is None:
        raise KeyError(key)
    if key == DEFAULT_UNIVERSE_KEY:
        symbols, sectors = select_universe()
    else:
        symbols = builtin_symbols(key)
        sectors = sectors_for(symbols)
    return ResolvedUniverse(
        key=definition.key,
        label=definition.label,
        kind=UniverseKind.BUILTIN,
        symbols=tuple(symbols),
        sectors=sectors,
    )
