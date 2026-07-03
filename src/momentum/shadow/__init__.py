"""Shadow Trading Mode — the strategy proves itself before a single live order.

While shadow mode is enabled, every scan **generates** the orders the
strategy would place (same conviction ranking, same caps, same plans as
autopilot) but **never submits them anywhere** — not to the paper journal,
not to the venue, and structurally never to a live broker. Expected fills
are modeled from the live bar (spread crossed + participation slippage),
open shadow trades are managed on every scan (stop / target / breakeven
raise), and the ledger grades the whole idea over a 60-trading-day window:
execution accuracy (slippage estimates), expected P&L, exits, and the
opportunities the caps left on the table.
"""

from momentum.shadow.config import ShadowConfig, default_config
from momentum.shadow.engine import expected_fill, manage_shadow_trade
from momentum.shadow.reports import shadow_report

__all__ = [
    "ShadowConfig",
    "default_config",
    "expected_fill",
    "manage_shadow_trade",
    "shadow_report",
]
