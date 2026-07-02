"""Positions table.

By design, positions are never persisted as rows: the ``trades`` table is the
single source of truth and live positions are reconstructed from it
(:mod:`momentum.orchestration.recovery`, :mod:`momentum.portfolio.position`).
"""
