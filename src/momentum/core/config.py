"""Typed, validated configuration (Pydantic) loaded from YAML + environment.

Single source of truth for every tunable parameter (strategy, risk, data,
execution). Configs are immutable at runtime and hashed so any run can be
reproduced from its recorded config hash.

Architecture scaffold only — interface contract described below; NO implementation yet.
See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""
