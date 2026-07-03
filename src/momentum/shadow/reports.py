"""Shadow-mode reporting — execution accuracy, P&L, exits, missed setups.

Pure aggregation over shadow-trade rows (as plain dicts) inside the
proving window. Nothing is invented: with no closed trades the P&L block
says so, and the day counter states plainly how far through the 60
trading days the proof is.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from momentum.shadow.config import ShadowConfig


def _p50_p95(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    ordered = sorted(values)
    return (
        ordered[len(ordered) // 2],
        ordered[int(0.95 * (len(ordered) - 1))],
    )


def shadow_report(
    trades: list[dict[str, Any]],
    *,
    now: dt.datetime,
    candidates_seen: int,
    config: ShadowConfig | None = None,
) -> dict[str, Any]:
    """The full shadow verdict from the ledger (window-scoped by the caller)."""
    cfg = config or ShadowConfig()

    closed = [t for t in trades if t["status"] == "closed"]
    open_trades = [t for t in trades if t["status"] == "open"]

    # Execution accuracy: how far modeled fills sit from the decision price.
    entry_slips = [abs(float(t["entry_slippage_bps"])) for t in trades]
    exit_slips = [
        abs(float(t["exit_slippage_bps"])) for t in closed if t.get("exit_slippage_bps") is not None
    ]
    entry_p50, entry_p95 = _p50_p95(entry_slips)
    exit_p50, exit_p95 = _p50_p95(exit_slips)

    pnls = [float(t["expected_pnl"]) for t in closed if t.get("expected_pnl") is not None]
    rs = [float(t["expected_r"]) for t in closed if t.get("expected_r") is not None]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p <= 0]
    exit_reasons: dict[str, int] = {}
    for t in closed:
        reason = str(t.get("exit_reason") or "unknown")
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    trading_days = {
        str(t["entered_at"])[:10] for t in trades if t.get("entered_at") is not None
    } | {str(t["last_eval_at"])[:10] for t in trades if t.get("last_eval_at") is not None}

    return {
        "generated_at": now.isoformat(),
        "window_trading_days": cfg.window_trading_days,
        "trading_days_observed": len(trading_days),
        "window_complete": len(trading_days) >= cfg.window_trading_days,
        "orders_generated": len(trades),
        "orders_submitted": 0,  # by construction — shadow never submits
        "open": len(open_trades),
        "closed": len(closed),
        "execution_accuracy": {
            "entry_slippage_bps_p50": entry_p50,
            "entry_slippage_bps_p95": entry_p95,
            "exit_slippage_bps_p50": exit_p50,
            "exit_slippage_bps_p95": exit_p95,
            "fills_modeled": len(entry_slips) + len(exit_slips),
        },
        "pnl": {
            "expected_total": round(sum(pnls), 2) if pnls else None,
            "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
            "win_rate": round(len(winners) / len(pnls), 3) if pnls else None,
            "profit_factor": (
                round(sum(winners) / abs(sum(losers)), 3) if winners and losers else None
            ),
            "largest_winner": round(max(pnls), 2) if pnls else None,
            "largest_loser": round(min(pnls), 2) if pnls else None,
        },
        "exits": exit_reasons,
        "missed_opportunities": {
            "candidates_above_floor": candidates_seen,
            "orders_generated": len(trades),
            "left_on_the_table": max(candidates_seen - len(trades), 0),
        },
    }
