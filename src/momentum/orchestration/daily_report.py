"""The daily orchestration report: one auditable summary of a session's activity.

:class:`DailyReport` captures what the engine did on a given trading day — equity
before/after, the trades opened and closed, realised/unrealised P&L and the
entry-decision tally — and renders it as a dict (for persistence/JSON) or
markdown (for a human or the desktop app).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class DailyReport:
    """Summary of one daily orchestration run."""

    run_id: str
    as_of: dt.date
    mode: str
    equity_start: float
    equity_end: float
    cash_end: float
    realized_pnl: float
    unrealized_pnl: float
    num_open_positions: int
    opened: tuple[dict[str, Any], ...] = ()
    closed: tuple[dict[str, Any], ...] = ()
    entry_outcomes: dict[str, int] = field(default_factory=dict)

    @property
    def num_opened(self) -> int:
        return len(self.opened)

    @property
    def num_closed(self) -> int:
        return len(self.closed)

    @property
    def day_pnl(self) -> float:
        return self.equity_end - self.equity_start

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "as_of": self.as_of.isoformat(),
            "mode": self.mode,
            "equity_start": round(self.equity_start, 2),
            "equity_end": round(self.equity_end, 2),
            "cash_end": round(self.cash_end, 2),
            "day_pnl": round(self.day_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "num_open_positions": self.num_open_positions,
            "num_opened": self.num_opened,
            "num_closed": self.num_closed,
            "opened": list(self.opened),
            "closed": list(self.closed),
            "entry_outcomes": dict(self.entry_outcomes),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Daily Report — {self.as_of.isoformat()} ({self.mode})",
            "",
            f"- **Run:** `{self.run_id}`",
            f"- **Equity:** {self.equity_start:,.2f} → {self.equity_end:,.2f} "
            f"({self.day_pnl:+,.2f})",
            f"- **Cash:** {self.cash_end:,.2f}",
            f"- **Realised P&L:** {self.realized_pnl:+,.2f} | "
            f"**Unrealised:** {self.unrealized_pnl:+,.2f}",
            f"- **Open positions:** {self.num_open_positions}",
            f"- **Opened today:** {self.num_opened} | **Closed today:** {self.num_closed}",
            "",
        ]
        if self.opened:
            lines.append("## Opened")
            for o in self.opened:
                lines.append(
                    f"- {o.get('symbol')}: {o.get('approved_shares')} sh @ "
                    f"{_fmt(o.get('entry_price'))} "
                    f"(conviction {o.get('conviction_band')} {_fmt(o.get('conviction_score'))})"
                )
            lines.append("")
        if self.closed:
            lines.append("## Closed")
            for c in self.closed:
                lines.append(
                    f"- {c.get('symbol')}: {c.get('reason')} @ {_fmt(c.get('exit_price'))} "
                    f"→ net {_fmt(c.get('net_pnl'))} (R {_fmt(c.get('r_multiple'))})"
                )
            lines.append("")
        if self.entry_outcomes:
            tally = ", ".join(f"{k}={v}" for k, v in sorted(self.entry_outcomes.items()))
            lines.append(f"## Entry decisions\n\n{tally}\n")
        return "\n".join(lines)


def tally_outcomes(outcomes: list[str]) -> dict[str, int]:
    """Count entry-decision outcomes (e.g. opened / vetoed / rejected_conviction)."""
    return dict(Counter(outcomes))


def _fmt(value: Any) -> str:
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "—"
