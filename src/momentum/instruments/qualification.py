"""The options-qualification engine — a hard gate on option tradeability.

``OptionsQualificationEngine.qualify(quote)`` takes a single :class:`OptionQuote`
(one contract's market snapshot) and returns an :class:`OptionsQualification`
verdict — ``QUALIFIED`` or ``REJECTED`` — with a per-gate breakdown and a
human-readable reason for every failure.

A trade may only be expressed with this option when it clears **all** of:

1. **Open interest** > floor — enough resting contracts to enter/exit.
2. **Bid/ask spread** < ceiling (as a fraction of mid) — tight enough to trade.
3. **Volume** > floor — actually trading today.
4. **Days to expiration** > floor — not in the expiration-week theta/pin zone.
5. **Implied volatility** < ceiling — not a blow-off / un-hedgeable premium.
6. **Gamma risk** acceptable — delta is stable enough to manage.

Every gate is evaluated (no short-circuit) so the verdict lists *all* reasons a
contract was rejected, not just the first. The engine is pure and depends only
on ``core`` — sizing and routing stay with ``risk/`` and ``execution/``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from momentum.core.enums import QualificationVerdict
from momentum.instruments.qualification_config import OptionsQualificationConfig


@dataclass(frozen=True, slots=True)
class OptionQuote:
    """A single option contract's market snapshot — the gate's input.

    ``implied_vol`` is the annualized ATM-equivalent IV as a fraction (``0.45`` =
    45%). ``gamma`` is per-share (dDelta/dS) and, together with
    ``underlying_price``, drives the gamma-risk gate; both are optional and the
    gate degrades gracefully when they are absent (see ``require_greeks``).
    """

    symbol: str  # underlying ticker
    days_to_expiry: int
    open_interest: float
    volume: float
    bid: float
    ask: float
    implied_vol: float  # annualized fraction (0.45 = 45%)
    # --- optional greeks / context ---------------------------------------- #
    gamma: float | None = None  # per-share dDelta/dS
    delta: float | None = None  # per-share, reported for context (not gated)
    underlying_price: float | None = None  # spot, for the gamma-shock measure
    strike: float | None = None
    right: str = "call"
    contract_symbol: str | None = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def has_two_sided_market(self) -> bool:
        """A genuine, uncrossed quote on both sides."""
        return self.bid > 0.0 and self.ask > 0.0 and self.ask >= self.bid

    @property
    def spread_pct(self) -> float:
        """Bid/ask spread as a fraction of mid (``inf`` with no two-sided market)."""
        if not self.has_two_sided_market:
            return math.inf
        return self.spread / self.mid


@dataclass(frozen=True, slots=True)
class GateCheck:
    """One gate's outcome — pass/fail, the measured value and its threshold."""

    name: str
    passed: bool
    detail: str
    value: float | None = None
    threshold: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "value": _round(self.value),
            "threshold": _round(self.threshold),
        }


@dataclass(frozen=True, slots=True)
class OptionsQualification:
    """The auditable verdict for one option contract."""

    verdict: QualificationVerdict
    symbol: str
    checks: tuple[GateCheck, ...]
    mid: float
    spread_pct: float

    @property
    def qualified(self) -> bool:
        return self.verdict.is_qualified

    @property
    def rejected(self) -> bool:
        return not self.verdict.is_qualified

    @property
    def reasons(self) -> tuple[str, ...]:
        """Human-readable details of the gates that failed (empty when qualified)."""
        return tuple(c.detail for c in self.checks if not c.passed)

    @property
    def failed_gates(self) -> tuple[str, ...]:
        """Names of the gates that failed."""
        return tuple(c.name for c in self.checks if not c.passed)

    def check(self, name: str) -> GateCheck | None:
        """The :class:`GateCheck` for a named gate, if present."""
        return next((c for c in self.checks if c.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "symbol": self.symbol,
            "qualified": self.qualified,
            "mid": _round(self.mid, 4),
            "spread_pct": _round(self.spread_pct, 4),
            "reasons": list(self.reasons),
            "failed_gates": list(self.failed_gates),
            "checks": [c.to_dict() for c in self.checks],
        }

    def __str__(self) -> str:
        if self.qualified:
            return f"<Options QUALIFIED {self.symbol}>"
        return f"<Options REJECTED {self.symbol}: {'; '.join(self.reasons)}>"


class OptionsQualificationEngine:
    """Vets an option contract against every hard tradeability gate."""

    def __init__(self, config: OptionsQualificationConfig | None = None) -> None:
        self.config = config or OptionsQualificationConfig()

    # -- public API --------------------------------------------------------- #
    def qualify(self, quote: OptionQuote) -> OptionsQualification:
        cfg = self.config
        checks = (
            self._open_interest(quote, cfg),
            self._spread(quote, cfg),
            self._volume(quote, cfg),
            self._days_to_expiry(quote, cfg),
            self._implied_vol(quote, cfg),
            self._gamma(quote, cfg),
        )
        verdict = (
            QualificationVerdict.QUALIFIED
            if all(c.passed for c in checks)
            else QualificationVerdict.REJECTED
        )
        return OptionsQualification(
            verdict=verdict,
            symbol=quote.symbol.upper(),
            checks=checks,
            mid=quote.mid,
            spread_pct=quote.spread_pct,
        )

    def is_qualified(self, quote: OptionQuote) -> bool:
        """Convenience boolean for callers that only need the verdict."""
        return self.qualify(quote).qualified

    # -- gates -------------------------------------------------------------- #
    @staticmethod
    def _open_interest(q: OptionQuote, cfg: OptionsQualificationConfig) -> GateCheck:
        ok = q.open_interest > cfg.min_open_interest
        detail = (
            f"open interest {q.open_interest:,.0f} above floor {cfg.min_open_interest:,.0f}"
            if ok
            else f"open interest {q.open_interest:,.0f} at/below floor {cfg.min_open_interest:,.0f}"
        )
        return GateCheck("open_interest", ok, detail, q.open_interest, cfg.min_open_interest)

    @staticmethod
    def _spread(q: OptionQuote, cfg: OptionsQualificationConfig) -> GateCheck:
        if not q.has_two_sided_market:
            return GateCheck(
                "bid_ask_spread",
                False,
                "no two-sided market (missing or crossed bid/ask)",
                None,
                cfg.max_spread_pct,
            )
        ok = q.spread_pct < cfg.max_spread_pct
        detail = (
            f"bid/ask spread {q.spread_pct:.1%} of mid under {cfg.max_spread_pct:.1%}"
            if ok
            else f"bid/ask spread {q.spread_pct:.1%} of mid at/above {cfg.max_spread_pct:.1%}"
        )
        return GateCheck("bid_ask_spread", ok, detail, q.spread_pct, cfg.max_spread_pct)

    @staticmethod
    def _volume(q: OptionQuote, cfg: OptionsQualificationConfig) -> GateCheck:
        ok = q.volume > cfg.min_volume
        detail = (
            f"volume {q.volume:,.0f} above floor {cfg.min_volume:,.0f}"
            if ok
            else f"volume {q.volume:,.0f} at/below floor {cfg.min_volume:,.0f}"
        )
        return GateCheck("volume", ok, detail, q.volume, cfg.min_volume)

    @staticmethod
    def _days_to_expiry(q: OptionQuote, cfg: OptionsQualificationConfig) -> GateCheck:
        ok = q.days_to_expiry > cfg.min_days_to_expiry
        detail = (
            f"{q.days_to_expiry} days to expiry above floor {cfg.min_days_to_expiry}"
            if ok
            else f"{q.days_to_expiry} days to expiry at/below floor {cfg.min_days_to_expiry}"
        )
        return GateCheck(
            "days_to_expiry", ok, detail, float(q.days_to_expiry), float(cfg.min_days_to_expiry)
        )

    @staticmethod
    def _implied_vol(q: OptionQuote, cfg: OptionsQualificationConfig) -> GateCheck:
        ok = q.implied_vol < cfg.max_implied_vol
        detail = (
            f"implied vol {q.implied_vol:.0%} under ceiling {cfg.max_implied_vol:.0%}"
            if ok
            else f"implied vol {q.implied_vol:.0%} at/above ceiling {cfg.max_implied_vol:.0%}"
        )
        return GateCheck("implied_vol", ok, detail, q.implied_vol, cfg.max_implied_vol)

    @staticmethod
    def _gamma(q: OptionQuote, cfg: OptionsQualificationConfig) -> GateCheck:
        name = "gamma_risk"
        if q.gamma is None or q.underlying_price is None or q.underlying_price <= 0:
            if cfg.require_greeks:
                return GateCheck(
                    name,
                    False,
                    "gamma/underlying unavailable and greeks are required",
                    None,
                    cfg.max_gamma_shock_delta,
                )
            return GateCheck(
                name,
                True,
                "gamma risk not evaluated (gamma/underlying unavailable)",
                None,
                cfg.max_gamma_shock_delta,
            )
        shock_delta = abs(q.gamma) * q.underlying_price * cfg.gamma_shock_pct
        ok = shock_delta <= cfg.max_gamma_shock_delta
        detail = (
            f"gamma risk Δδ={shock_delta:.2f} on a {cfg.gamma_shock_pct:.0%} move "
            f"{'within' if ok else 'over'} limit {cfg.max_gamma_shock_delta:.2f}"
        )
        return GateCheck(name, ok, detail, shock_delta, cfg.max_gamma_shock_delta)


def _round(value: float | None, ndigits: int = 6) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, ndigits)
