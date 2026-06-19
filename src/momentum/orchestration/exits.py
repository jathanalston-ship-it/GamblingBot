"""Exit management: decide when an open position should be closed.

The rules are pure and ordered by priority: a protective **stop** first (risk is
always honoured first), then a profit **target** expressed in R, then a **time
stop** on holding period. :func:`evaluate_exit` returns a single
:class:`ExitSignal` (or ``None``) for one position; :class:`ExitManager` applies
it across the book given current marks.

Config is immutable Pydantic loadable from ``config/exits.example.yaml``. All
thresholds are optional — an unset rule simply never fires.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from momentum.portfolio.position import Position

# Exit reasons (fit Trade.exit_reason, String(24)).
STOP = "stop"
TARGET = "target"
TIME_STOP = "time_stop"


class ExitConfig(BaseModel):
    """Thresholds for the exit rules (an unset rule never fires)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    use_stop: bool = True
    # Exit when price trades through the position's protective stop.
    target_r: float | None = Field(default=None, gt=0.0)
    # Exit when unrealised gain reaches this many R (None = no profit target).
    max_holding_days: int | None = Field(default=None, ge=0)
    # Exit after this many calendar days held (None = no time stop).

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExitConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ExitConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class ExitSignal:
    """A decision to close one position."""

    symbol: str
    reason: str  # STOP | TARGET | TIME_STOP
    price: float
    quantity: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "reason": self.reason,
            "price": self.price,
            "quantity": self.quantity,
        }


def evaluate_exit(
    position: Position, price: float, as_of: dt.date, config: ExitConfig
) -> ExitSignal | None:
    """Return an exit signal for ``position`` at ``price``, or ``None`` to hold."""
    if not position.is_open or position.side is None:
        return None
    sign = position.side.sign

    if config.use_stop and position.stop is not None:
        through_stop = (price <= position.stop) if sign > 0 else (price >= position.stop)
        if through_stop:
            return ExitSignal(position.symbol, STOP, price, position.quantity)

    risk = position.initial_risk
    if config.target_r is not None and risk:
        r_at_price = sign * (price - position.avg_price) * position.quantity / risk
        if r_at_price >= config.target_r:
            return ExitSignal(position.symbol, TARGET, price, position.quantity)

    if config.max_holding_days is not None and position.opened_ts is not None:
        held_days = (as_of - position.opened_ts.date()).days
        if held_days >= config.max_holding_days:
            return ExitSignal(position.symbol, TIME_STOP, price, position.quantity)

    return None


class ExitManager:
    """Applies the exit rules across a set of open positions."""

    def __init__(self, config: ExitConfig | None = None) -> None:
        self.config = config or ExitConfig()

    def exits(
        self, positions: list[Position], marks: dict[str, float], as_of: dt.date
    ) -> list[ExitSignal]:
        """Exit signals for every position that has a current mark and should close."""
        signals: list[ExitSignal] = []
        for position in positions:
            price = marks.get(position.symbol)
            if price is None:
                continue
            signal = evaluate_exit(position, price, as_of, self.config)
            if signal is not None:
                signals.append(signal)
        return signals
