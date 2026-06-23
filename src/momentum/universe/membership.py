"""Universe selection — the tradeable symbol set the scanner fetches and ranks.

The symbols are NOT hardcoded in any action: they come from configuration
(``config/universe_symbols.yaml`` under ``MRP_USER_DIR`` if the user edits it, else
the shipped ``universe_symbols.example.yaml``, else the in-code default below — same
resolution as every other engine, via :mod:`momentum.core.config_paths`). Edit the
config to change coverage; the scanner applies price/liquidity filters on top.

``select_universe`` returns ``(symbols, sectors)`` — the list of tickers to pull
and a ``symbol -> GICS sector`` map the scanner uses for sector relative strength.
"""

from __future__ import annotations

from typing import Any

from momentum.core.config_paths import load_config

UNIVERSE_FILE = "universe_symbols.example.yaml"

# The default tradeable universe: large-cap, highly liquid US equities (S&P 100
# style). A real, broad universe — not a demo handful — so a live scan ranks a
# meaningful cross-section. Editable via config; this is only the fallback default.
_EMBEDDED_MEMBERS: list[tuple[str, str]] = [
    ("AAPL", "Information Technology"),
    ("MSFT", "Information Technology"),
    ("NVDA", "Information Technology"),
    ("AVGO", "Information Technology"),
    ("ORCL", "Information Technology"),
    ("CRM", "Information Technology"),
    ("ADBE", "Information Technology"),
    ("AMD", "Information Technology"),
    ("ACN", "Information Technology"),
    ("CSCO", "Information Technology"),
    ("IBM", "Information Technology"),
    ("INTC", "Information Technology"),
    ("QCOM", "Information Technology"),
    ("TXN", "Information Technology"),
    ("NOW", "Information Technology"),
    ("INTU", "Information Technology"),
    ("AMAT", "Information Technology"),
    ("MU", "Information Technology"),
    ("AMZN", "Consumer Discretionary"),
    ("TSLA", "Consumer Discretionary"),
    ("HD", "Consumer Discretionary"),
    ("MCD", "Consumer Discretionary"),
    ("NKE", "Consumer Discretionary"),
    ("LOW", "Consumer Discretionary"),
    ("SBUX", "Consumer Discretionary"),
    ("BKNG", "Consumer Discretionary"),
    ("TJX", "Consumer Discretionary"),
    ("GM", "Consumer Discretionary"),
    ("F", "Consumer Discretionary"),
    ("GOOGL", "Communication Services"),
    ("META", "Communication Services"),
    ("NFLX", "Communication Services"),
    ("DIS", "Communication Services"),
    ("CMCSA", "Communication Services"),
    ("T", "Communication Services"),
    ("VZ", "Communication Services"),
    ("TMUS", "Communication Services"),
    ("JPM", "Financials"),
    ("BAC", "Financials"),
    ("WFC", "Financials"),
    ("GS", "Financials"),
    ("MS", "Financials"),
    ("C", "Financials"),
    ("AXP", "Financials"),
    ("BLK", "Financials"),
    ("SCHW", "Financials"),
    ("SPGI", "Financials"),
    ("BRK-B", "Financials"),
    ("V", "Financials"),
    ("MA", "Financials"),
    ("LLY", "Health Care"),
    ("UNH", "Health Care"),
    ("JNJ", "Health Care"),
    ("ABBV", "Health Care"),
    ("MRK", "Health Care"),
    ("PFE", "Health Care"),
    ("TMO", "Health Care"),
    ("ABT", "Health Care"),
    ("DHR", "Health Care"),
    ("BMY", "Health Care"),
    ("AMGN", "Health Care"),
    ("MDT", "Health Care"),
    ("GILD", "Health Care"),
    ("CVS", "Health Care"),
    ("XOM", "Energy"),
    ("CVX", "Energy"),
    ("COP", "Energy"),
    ("SLB", "Energy"),
    ("EOG", "Energy"),
    ("PG", "Consumer Staples"),
    ("KO", "Consumer Staples"),
    ("PEP", "Consumer Staples"),
    ("COST", "Consumer Staples"),
    ("WMT", "Consumer Staples"),
    ("PM", "Consumer Staples"),
    ("MDLZ", "Consumer Staples"),
    ("CL", "Consumer Staples"),
    ("TGT", "Consumer Staples"),
    ("HON", "Industrials"),
    ("CAT", "Industrials"),
    ("BA", "Industrials"),
    ("GE", "Industrials"),
    ("UPS", "Industrials"),
    ("RTX", "Industrials"),
    ("UNP", "Industrials"),
    ("DE", "Industrials"),
    ("LMT", "Industrials"),
    ("MMM", "Industrials"),
    ("LIN", "Materials"),
    ("APD", "Materials"),
    ("SHW", "Materials"),
    ("NEE", "Utilities"),
    ("DUK", "Utilities"),
    ("SO", "Utilities"),
    ("AMT", "Real Estate"),
    ("PLD", "Real Estate"),
]

# JSON-able default for config bootstrap (mirrors universe_symbols.example.yaml).
_EMBEDDED_UNIVERSE: dict[str, Any] = {
    "members": [{"symbol": s, "sector": sec} for s, sec in _EMBEDDED_MEMBERS],
}


def select_universe() -> tuple[list[str], dict[str, str]]:
    """The configured tradeable universe: ``(symbols, {symbol: sector})``.

    Loads from config (user override → shipped example → embedded default) and
    de-duplicates, preserving order. Never hardcoded in a calling action.
    """
    data = load_config(UNIVERSE_FILE, embedded=_EMBEDDED_UNIVERSE)
    members = data.get("members") if isinstance(data, dict) else None
    if not isinstance(members, list):
        members = _EMBEDDED_UNIVERSE["members"]

    symbols: list[str] = []
    sectors: dict[str, str] = {}
    seen: set[str] = set()
    for m in members:
        if not isinstance(m, dict):
            continue
        sym = str(m.get("symbol", "")).strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        symbols.append(sym)
        sec = m.get("sector")
        if sec:
            sectors[sym] = str(sec)
    return symbols, sectors
