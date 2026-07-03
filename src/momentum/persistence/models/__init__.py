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

from momentum.persistence.models.activity import Activity
from momentum.persistence.models.alert import Alert
from momentum.persistence.models.audit_log import AuditLog
from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin
from momentum.persistence.models.broker import (
    BrokerAccount,
    BrokerAccountHistory,
    BrokerFill,
    BrokerOrderEvent,
    BrokerOrderRow,
    BrokerPosition,
)
from momentum.persistence.models.candidate_analog import CandidateAnalog
from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.models.fill import FillRecord
from momentum.persistence.models.instrument_selection import InstrumentSelection
from momentum.persistence.models.market_regime import MarketRegime
from momentum.persistence.models.market_data_provenance import MarketDataProvenance
from momentum.persistence.models.opportunity_classification import OpportunityClassification
from momentum.persistence.models.optimization_result import OptimizationResult
from momentum.persistence.models.order import OrderRecord
from momentum.persistence.models.portfolio_snapshot import PortfolioSnapshot
from momentum.persistence.models.position_size import PositionSize
from momentum.persistence.models.research_report import ResearchReport
from momentum.persistence.models.risk_metric import RiskMetric
from momentum.persistence.models.run import Run
from momentum.persistence.models.scan_delta import ScanDelta
from momentum.persistence.models.scan_metadata import ScanMetadata
from momentum.persistence.models.scan_rejection import ScanRejection
from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.models.scan_snapshot import ScanSnapshot
from momentum.persistence.models.scan_stat import ScanStat
from momentum.persistence.models.signal import Signal
from momentum.persistence.models.trade_plan import TradePlan
from momentum.persistence.models.setup_lifecycle import SetupLifecycle
from momentum.persistence.models.tracked_trade import TrackedTrade
from momentum.persistence.models.trade import Trade
from momentum.persistence.models.trade_evaluation import TradeEvaluation
from momentum.persistence.models.user_universe import UserUniverse
from momentum.persistence.models.watchlist_entry import WatchlistEntryRow
from momentum.persistence.models.watchlist_performance import WatchlistPerformance

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
    "WatchlistEntryRow",
    "WatchlistPerformance",
    "SetupLifecycle",
    "UserUniverse",
    "ScanMetadata",
    "ScanRejection",
    "TradePlan",
    "CandidateAnalog",
    "MarketDataProvenance",
    "TrackedTrade",
    "TradeEvaluation",
    "ScanSnapshot",
    "ScanDelta",
    "Alert",
    "Activity",
    "ScanStat",
    "OrderRecord",
    "FillRecord",
    "BrokerAccount",
    "BrokerAccountHistory",
    "BrokerOrderRow",
    "BrokerOrderEvent",
    "BrokerFill",
    "BrokerPosition",
]
