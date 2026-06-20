"""Setup-lifecycle tracking: every candidate lives in exactly one state.

Building → Ready → Triggered → Active → Extended, with terminal Completed /
Failed. States are derived automatically from each candidate's evidence (scan,
conviction, entry signal, open/closed trade) by the pure :class:`LifecycleEngine`
and persisted with a transition history.
"""

from __future__ import annotations

from momentum.lifecycle.config import LifecycleConfig, default_config
from momentum.lifecycle.engine import LifecycleEngine
from momentum.lifecycle.types import (
    STATE_ORDER,
    LifecycleEvaluation,
    LifecycleInputs,
    LifecycleState,
)

__all__ = [
    "STATE_ORDER",
    "LifecycleConfig",
    "LifecycleEngine",
    "LifecycleEvaluation",
    "LifecycleInputs",
    "LifecycleState",
    "default_config",
]
