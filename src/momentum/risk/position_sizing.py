"""Position sizing: signal + stop distance + equity -> share quantity.

Strategies: fixed-fractional risk (risk R% of equity per trade), volatility
targeting (size to a target annualized vol contribution), and fractional Kelly
(capped). Risk-per-trade is the primary lever; sizing never widens stops.

Architecture scaffold only — interface contract described below; NO implementation yet.
See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""
