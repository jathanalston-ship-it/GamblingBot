"""Exit management: decide when an open position should be closed or reduced.

The rules are pure and ordered by priority: a protective **stop** first (risk is
always honoured first), then a profit **target** expressed in R, then a partial
**scale-out** at a lower R, then a **time stop** on holding period.
:func:`evaluate_exit` returns a single :class:`ExitSignal` (or ``None``) for one
position; :func:`trailing_stop` proposes a ratcheted stop (never loosened);
:class:`ExitManager` applies both across the book given current marks.

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
from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.portfolio.position import Position

# Exit reasons (fit Trade.exit_reason, String(24)).
STOP = "stop"
TRAILING_STOP = "trailing_stop"
TARGET = "target"
SCALE_OUT = "scale_out"
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
    trailing_stop_pct: float | None = Field(default=None, gt=0.0, lt=1.0)
    # Ratchet the stop to this fraction below the mark (longs; above for
    # shorts). Stops only ever tighten — never loosen (None = no trailing).
    scale_out_r: float | None = Field(default=None, gt=0.0)
    # Take partial profits once at this many R (None = no scale-out).
    scale_out_fraction: float = Field(default=0.5, gt=0.0, lt=1.0)
    # Fraction of the position to sell when the scale-out fires.

    @model_validator(mode="after")
    def _scale_out_below_target(self) -> ExitConfig:
        if (
            self.scale_out_r is not None
            and self.target_r is not None
            and self.scale_out_r >= self.target_r
        ):
            raise ValueError(
                f"scale_out_r ({self.scale_out_r}) must be below target_r ({self.target_r})"
            )
        return self

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
    """A decision to close (or partially close) one position."""

    symbol: str
    reason: str  # STOP | TRAILING_STOP | TARGET | SCALE_OUT | TIME_STOP
    price: float
    quantity: int

    @property
    def is_partial(self) -> bool:
        return self.reason == SCALE_OUT

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "reason": self.reason,
            "price": self.price,
            "quantity": self.quantity,
        }


def trailing_stop(position: Position, price: float, config: ExitConfig) -> float | None:
    """A tightened stop for ``position`` at ``price``, or ``None`` to leave it.

    The proposed stop trails ``trailing_stop_pct`` below the mark (above, for
    shorts) and is only returned when it is *tighter* than the current stop —
    a trailing stop ratchets, it never loosens. Marks only ever tighten it, so
    the ratchet tracks the position's high-water mark without storing one.
    """
    if config.trailing_stop_pct is None or not position.is_open or position.side is None:
        return None
    sign = position.side.sign
    proposed = price * (1.0 - sign * config.trailing_stop_pct)
    current = position.stop
    if current is None or sign * (proposed - current) > 0:
        return round(proposed, 4)
    return None


def _scale_out_quantity(position: Position, fraction: float) -> int | None:
    """Shares to sell for a partial scale-out, or ``None`` if it can't be partial."""
    quantity = int(position.quantity * fraction)
    if quantity < 1 or quantity >= position.quantity:
        return None  # a 1-share position can't scale out — leave it to the full exits
    return quantity


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
            # A stop that has been ratcheted tighter than the initial one is a
            # trailing-stop exit (profit protection), not the original risk stop.
            tightened = (
                position.initial_stop is not None
                and sign * (position.stop - position.initial_stop) > 0
            )
            reason = TRAILING_STOP if tightened else STOP
            return ExitSignal(position.symbol, reason, price, position.quantity)

    risk = position.initial_risk
    # R here is per-share (quantity cancels between numerator and initial_risk),
    # so it stays correct after a partial scale-out changes position.quantity.
    r_at_price = (
        sign * (price - position.avg_price) * position.initial_quantity / risk if risk else None
    )

    if config.target_r is not None and r_at_price is not None and r_at_price >= config.target_r:
        return ExitSignal(position.symbol, TARGET, price, position.quantity)

    if (
        config.scale_out_r is not None
        and r_at_price is not None
        and r_at_price >= config.scale_out_r
        and position.quantity == position.initial_quantity  # fires once, at full size
    ):
        quantity = _scale_out_quantity(position, config.scale_out_fraction)
        if quantity is not None:
            return ExitSignal(position.symbol, SCALE_OUT, price, quantity)

    if config.max_holding_days is not None and position.opened_ts is not None:
        held_days = (as_of - position.opened_ts.date()).days
        if held_days >= config.max_holding_days:
            return ExitSignal(position.symbol, TIME_STOP, price, position.quantity)

    return None


class ExitManager:
    """Applies the exit rules across a set of open positions."""

    def __init__(self, config: ExitConfig | None = None) -> None:
        self.config = config or ExitConfig()

    def stop_adjustments(
        self, positions: list[Position], marks: dict[str, float]
    ) -> dict[str, float]:
        """Tightened trailing stops per symbol (apply these *before* exits)."""
        adjustments: dict[str, float] = {}
        for position in positions:
            price = marks.get(position.symbol)
            if price is None:
                continue
            new_stop = trailing_stop(position, price, self.config)
            if new_stop is not None:
                adjustments[position.symbol] = new_stop
        return adjustments

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
