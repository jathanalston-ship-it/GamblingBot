"""Stop policy — defines the 'R' unit of every trade.

Initial ATR-multiple stop, chandelier/trailing stop, breakeven move, and time
stop. Returns updated stop levels each bar so winners are let run and losers cut.

Architecture scaffold only — interface contract described below; NO implementation yet.
See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""
