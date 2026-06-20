"""Value objects for setup-lifecycle tracking."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LifecycleState(str, Enum):
    """The single state a candidate's setup is in."""

    BUILDING = "Building"  # setup forming
    READY = "Ready"  # conditions nearly met
    TRIGGERED = "Triggered"  # entry condition hit
    ACTIVE = "Active"  # trade in progress
    EXTENDED = "Extended"  # move has become crowded
    FAILED = "Failed"  # setup invalidated
    COMPLETED = "Completed"  # target reached


# Display / pipeline order (terminal states last).
STATE_ORDER: tuple[LifecycleState, ...] = (
    LifecycleState.BUILDING,
    LifecycleState.READY,
    LifecycleState.TRIGGERED,
    LifecycleState.ACTIVE,
    LifecycleState.EXTENDED,
    LifecycleState.COMPLETED,
    LifecycleState.FAILED,
)


@dataclass(frozen=True, slots=True)
class LifecycleInputs:
    """Evidence for one candidate, assembled from scan / conviction / trades."""

    symbol: str
    has_scan: bool = False
    passed_scan: bool = False
    conviction_score: float | None = None
    distance_from_ath: float | None = None  # signed fraction (0 = at ATH)
    relative_volume: float | None = None
    price: float | None = None
    support_level: float | None = None
    sector: str | None = None

    has_entry_signal: bool = False

    open_trade: bool = False
    open_entry_price: float | None = None
    open_risk_per_share: float | None = None

    closed_trade: bool = False
    closed_r: float | None = None
    closed_exit_reason: str | None = None

    prior_state: LifecycleState | None = None


@dataclass(frozen=True, slots=True)
class LifecycleEvaluation:
    """The derived state + a human reason."""

    symbol: str
    state: LifecycleState
    reason: str
