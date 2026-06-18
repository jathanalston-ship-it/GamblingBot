"""The RISK GATEWAY — single chokepoint for ALL risk policy.

evaluate(signal, portfolio, account) -> RiskAssessment {APPROVE | RESIZE | VETO}
with sized quantity, stop level and human-readable reasons. Composes volatility,
sizing, stops, exposure, correlation, heat, drawdown and limits in one auditable
pass. No order may be created without passing through here.

Architecture scaffold only — interface contract described below; NO implementation yet.
See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""
