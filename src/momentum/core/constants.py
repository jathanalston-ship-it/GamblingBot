"""System-wide constants.

Shared numeric conventions so volatility annualization, rounding and
float comparisons are consistent across every module.
"""

from __future__ import annotations

# Standard US-equity trading sessions per year (for annualizing vol/returns).
TRADING_DAYS_PER_YEAR = 252

# Rounding precision.
PRICE_PRECISION = 4  # dollars
QTY_PRECISION = 0  # whole shares (US equities)

# Numerical tolerance for float comparisons / divide-by-zero guards.
EPS = 1e-9
