"""FastAPI read service exposing the MRP research database.

Read-only by design: the API surfaces signals, trades, regimes, portfolio
snapshots, risk metrics, scans, optimization results and performance summaries,
but never mutates strategy, config or stored research.
"""

from __future__ import annotations

from momentum.api.app import create_app

__all__ = ["create_app"]
