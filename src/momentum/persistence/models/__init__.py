"""ORM models package.

Importing this package imports every model module, which registers all tables
on ``Base.metadata`` — required for ``Base.metadata.create_all(...)`` and for
Alembic autogeneration to "see" the full schema.

Implemented tables: market_regimes, signals, position_sizes, trades,
portfolio_snapshots, risk_metrics, optimization_results, scan_results,
research_reports, instrument_selections, conviction_scores,
opportunity_classifications, runs, audit_log.
"""

from __future__ import annotations

from momentum.persistence.models.audit_log import AuditLog
from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin
from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.models.instrument_selection import InstrumentSelection
from momentum.persistence.models.market_regime import MarketRegime
from momentum.persistence.models.opportunity_classification import OpportunityClassification
from momentum.persistence.models.optimization_result import OptimizationResult
from momentum.persistence.models.portfolio_snapshot import PortfolioSnapshot
from momentum.persistence.models.position_size import PositionSize
from momentum.persistence.models.research_report import ResearchReport
from momentum.persistence.models.risk_metric import RiskMetric
from momentum.persistence.models.run import Run
from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.models.signal import Signal
from momentum.persistence.models.trade import Trade

__all__ = [
    "Base",
    "IntPKMixin",
    "TimestampMixin",
    "ConvictionScore",
    "MarketRegime",
    "Signal",
    "ScanResult",
    "PositionSize",
    "Trade",
    "PortfolioSnapshot",
    "RiskMetric",
    "OptimizationResult",
    "ResearchReport",
    "InstrumentSelection",
    "OpportunityClassification",
    "Run",
    "AuditLog",
]
