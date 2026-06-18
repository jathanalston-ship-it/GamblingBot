"""Order matching against historical bars — the no-look-ahead execution core.

Two rules keep simulated fills honest:

1. **Next-bar-open execution.** An order decided on bar *t*'s close is filled at
   bar *t+1*'s **open** (plus slippage), never at any price from bar *t*. The
   engine enforces the one-bar delay; this module prices the fill.
2. **Gap risk is explicit.** A protective stop is not a guarantee. If a bar
   *opens* beyond the stop, the fill happens at that gapped open — a loss that
   can exceed the intended −1R. Only if the stop sits inside the bar's range is
   it filled at the stop level.
"""

from __future__ import annotations

from dataclasses import dataclass

from momentum.core.enums import Side
from momentum.execution.slippage import CommissionModel, SlippageModel


@dataclass(frozen=True, slots=True)
class Fill:
    """A simulated execution."""

    price: float
    shares: float
    commission: float
    gapped: bool = False

    @property
    def cash_flow(self) -> float:
        """Signed cash impact is applied by the engine; this is gross notional."""
        return self.price * self.shares


@dataclass(frozen=True, slots=True)
class StopResolution:
    """Whether/where a protective stop triggered on a bar."""

    triggered: bool
    exec_price: float
    gapped: bool


class MarketSimulator:
    """Prices fills against bars using shared slippage & commission models."""

    def __init__(
        self,
        commission: CommissionModel,
        slippage: SlippageModel,
        stop_slippage: SlippageModel | None = None,
    ) -> None:
        self.commission = commission
        self.slippage = slippage
        # Stops often fill worse than the trigger; default to the same model.
        self.stop_slippage = stop_slippage or slippage

    def fill_at(self, *, reference_price: float, shares: float, side: Side) -> Fill:
        """Fill ``shares`` at ``reference_price`` (a bar open) adjusted for slippage."""
        price = self.slippage.fill_price(reference_price, side)
        return Fill(price=price, shares=shares, commission=self.commission.cost(shares, price))

    def resolve_stop(
        self,
        *,
        position_side: Side,
        stop_price: float,
        bar_open: float,
        bar_high: float,
        bar_low: float,
        allow_gap: bool = True,
    ) -> StopResolution:
        """Did a protective stop trigger on this bar, and at what price?

        For a long the stop is below price; a gap-down open fills at the open
        (worse than the stop). Mirror logic for shorts.
        """
        if position_side is Side.LONG:
            if allow_gap and bar_open <= stop_price:
                return StopResolution(True, bar_open, gapped=True)  # gapped through
            if bar_low <= stop_price:
                return StopResolution(True, stop_price, gapped=False)
            return StopResolution(False, stop_price, gapped=False)
        # short position: protective stop is above price
        if allow_gap and bar_open >= stop_price:
            return StopResolution(True, bar_open, gapped=True)
        if bar_high >= stop_price:
            return StopResolution(True, stop_price, gapped=False)
        return StopResolution(False, stop_price, gapped=False)

    def fill_stop(self, *, exec_price: float, shares: float, exit_side: Side) -> Fill:
        """Price a stop exit, applying stop slippage in the exit direction."""
        price = self.stop_slippage.fill_price(exec_price, exit_side)
        return Fill(
            price=price,
            shares=shares,
            commission=self.commission.cost(shares, price),
            gapped=False,
        )
