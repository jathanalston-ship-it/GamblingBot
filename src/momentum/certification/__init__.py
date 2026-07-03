"""Paper Trading Certification — the gate before live trading is even discussed.

Grades 30 consecutive calendar days of continuous operation against hard
requirements (no crashes, no orphaned backend, no scheduler drift, no missed
scans, no duplicate trades, no database corruption, bounded memory, responsive
pipeline) and tracks the operational metrics (uptime, scans, trades, alerts,
errors, warnings, API/provider failures). **Never certifies until every
requirement passes over the full window.**
"""

from momentum.certification.config import CertificationConfig, default_config
from momentum.certification.engine import evaluate
from momentum.certification.types import (
    CertificationInputs,
    CertificationReport,
    Requirement,
)

__all__ = [
    "CertificationConfig",
    "CertificationInputs",
    "CertificationReport",
    "Requirement",
    "default_config",
    "evaluate",
]
