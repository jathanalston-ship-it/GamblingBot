"""Centralized RISK ENGINE — the core differentiator of this platform.

Every proposed trade flows through a single gateway (risk_manager.RiskManager)
that estimates volatility, sizes the position from risk-per-trade, sets stops,
and enforces exposure / correlation / heat / drawdown / hard limits BEFORE any
order can be created. Each decision is recorded as an auditable RiskAssessment.

Modules: volatility, position_sizing, stops, exposure, correlation, drawdown,
heat, limits, risk_manager.

Architecture scaffold only — interface contract described below; NO implementation yet.
See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""
