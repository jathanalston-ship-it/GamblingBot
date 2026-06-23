"""Canonical SQL for trade-intelligence reporting.

A library of named, parameterised analytical queries over the ``trades`` table —
the objective-first metrics expressed directly in SQL so they can run in any
client (the runner here, a BI tool, or ``sqlite3``/``psql``). Each query accepts
an optional ``:run_id`` (NULL = all runs) and considers only closed trades.

Conventions: ``r_multiple`` is P&L in R; ``mfe``/``mae`` are excursions in R, so
trend capture = Σ realised R ÷ Σ favourable excursion across winners.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# --- reusable SQL fragments ------------------------------------------------ #
_CLOSED = "status = 'closed' AND (:run_id IS NULL OR run_id = :run_id)"

# profit factor and expectancy in pure SQL (CASE keeps it SQLite-compatible)
_PROFIT_FACTOR = (
    "SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) / "
    "NULLIF(-SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END), 0)"
)
_WIN_RATE = "AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END)"
# Both sums gate on mfe > 0 (not just net_pnl > 0) to match the Python
# _trend_capture, which restricts to winners with positive MFE. Without the
# extra gate a winner with mfe = 0/NULL adds to the numerator but not the
# denominator, inflating the ratio relative to the reported Python metric.
_TREND_CAPTURE = (
    "SUM(CASE WHEN net_pnl > 0 AND mfe > 0 THEN r_multiple ELSE 0 END) / "
    "NULLIF(SUM(CASE WHEN net_pnl > 0 AND mfe > 0 THEN mfe ELSE 0 END), 0)"
)

_HOLD_BUCKET = (
    "CASE "
    "WHEN holding_days <= 1 THEN '0-1d' "
    "WHEN holding_days <= 5 THEN '2-5d' "
    "WHEN holding_days <= 20 THEN '6-20d' "
    "WHEN holding_days <= 60 THEN '21-60d' "
    "ELSE '60d+' END"
)


def _grouped(dimension: str) -> str:
    """A standard objective-first aggregate grouped by ``dimension``."""
    return f"""
        SELECT
            {dimension} AS bucket,
            COUNT(*)                         AS num_trades,
            AVG(r_multiple)                  AS expectancy_r,
            {_PROFIT_FACTOR}                 AS profit_factor,
            AVG(CASE WHEN net_pnl > 0 THEN r_multiple END) AS avg_winner_r,
            AVG(CASE WHEN net_pnl < 0 THEN r_multiple END) AS avg_loser_r,
            MAX(r_multiple)                  AS largest_winner_r,
            {_TREND_CAPTURE}                 AS trend_capture,
            {_WIN_RATE}                      AS win_rate,
            SUM(net_pnl)                     AS net_pnl,
            AVG(holding_days)                AS avg_holding_days
        FROM trades
        WHERE {_CLOSED}
        GROUP BY {dimension}
        ORDER BY expectancy_r DESC
    """


NAMED_QUERIES: dict[str, str] = {
    # Overall, objective-first summary.
    "overall_summary": f"""
        SELECT
            COUNT(*)                         AS num_trades,
            AVG(r_multiple)                  AS expectancy_r,
            {_PROFIT_FACTOR}                 AS profit_factor,
            AVG(CASE WHEN net_pnl > 0 THEN r_multiple END) AS avg_winner_r,
            AVG(CASE WHEN net_pnl < 0 THEN r_multiple END) AS avg_loser_r,
            MAX(r_multiple)                  AS largest_winner_r,
            MIN(r_multiple)                  AS largest_loser_r,
            {_TREND_CAPTURE}                 AS trend_capture,
            {_WIN_RATE}                      AS win_rate,
            SUM(net_pnl)                     AS net_pnl
        FROM trades
        WHERE {_CLOSED}
    """,
    "performance_by_sector": _grouped("sector"),
    "performance_by_regime": _grouped("regime_label"),
    "performance_by_entry_reason": _grouped("entry_reason"),
    "performance_by_exit_reason": _grouped("exit_reason"),
    "performance_by_holding_bucket": _grouped(_HOLD_BUCKET),
    # Does heavier entry-bar demand (relative volume) improve outcomes?
    "performance_by_relative_volume": _grouped(
        "CASE WHEN entry_relative_volume >= 2 THEN 'rvol>=2' "
        "WHEN entry_relative_volume >= 1 THEN 'rvol_1-2' ELSE 'rvol<1' END"
    ),
    # The fat right tail: the trades that carry the system.
    "top_winners": f"""
        SELECT symbol, sector, regime_label, entry_reason, exit_reason,
               entry_ts, exit_ts, holding_days, r_multiple, net_pnl, mfe, mae
        FROM trades
        WHERE {_CLOSED}
        ORDER BY r_multiple DESC
        LIMIT :limit
    """,
    # Excursion / stop research: how much favourable move we keep vs give back.
    "excursion_capture": f"""
        SELECT
            COUNT(*)        AS num_trades,
            AVG(mfe)        AS avg_mfe_r,
            AVG(mae)        AS avg_mae_r,
            AVG(r_multiple) AS avg_realised_r,
            {_TREND_CAPTURE} AS trend_capture
        FROM trades
        WHERE {_CLOSED}
    """,
    # Monthly net P&L for the equity-curve / heatmap tiles.
    "monthly_pnl": f"""
        SELECT
            strftime('%Y-%m', exit_ts) AS month,
            COUNT(*)                   AS num_trades,
            SUM(net_pnl)               AS net_pnl,
            AVG(r_multiple)            AS expectancy_r
        FROM trades
        WHERE {_CLOSED} AND exit_ts IS NOT NULL
        GROUP BY month
        ORDER BY month
    """,
}


def get_query(name: str) -> str:
    """Return the raw SQL for a named query."""
    try:
        return NAMED_QUERIES[name]
    except KeyError:
        raise KeyError(f"unknown query {name!r}; choose from {sorted(NAMED_QUERIES)}") from None


def run_query(
    session: Session,
    name: str,
    *,
    run_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Execute a named query and return rows as dicts."""
    stmt = text(get_query(name))
    params: dict[str, Any] = {"run_id": run_id}
    if ":limit" in NAMED_QUERIES[name]:
        params["limit"] = limit
    rows = session.execute(stmt, params).mappings().all()
    return [dict(r) for r in rows]
