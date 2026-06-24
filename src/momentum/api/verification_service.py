"""Runtime verification — prove the live pipeline works end to end, no mocks.

``status`` reports the runtime's health + the latest live counts. ``verify_pipeline``
pulls **one live symbol** from the configured provider and runs it through the
**actual runtime engines** — conviction, analog cohort, trade plan, watchlist —
reporting PASS/FAIL per stage. It never seeds, mocks or reads demo data; analog
cohorts come from real closed-trade history (``sample_size == 0`` is a legitimate
PASS, the stage ran).
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from momentum.analytics.trade_analysis import compute_trade_stats
from momentum.api import market_data_service, user_settings
from momentum.api.services import resolve_active_run_id
from momentum.conviction.engine import ConvictionEngine
from momentum.conviction.inputs import ConvictionInputs
from momentum.data.providers.base import MarketDataProvider
from momentum.data.schema import Timeframe, to_utc_timestamp
from momentum.persistence.models.candidate_analog import CandidateAnalog
from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.models.scan_metadata import ScanMetadata
from momentum.persistence.models.trade_plan import TradePlan
from momentum.persistence.models.watchlist_entry import WatchlistEntryRow
from momentum.persistence.repositories.trades import TradeRepository
from momentum.tradeplan import TradePlanEngine, TradePlanInputs
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner
from momentum.watchlist import WatchlistCandidate, WatchlistEngine

DEFAULT_VERIFY_SYMBOL = "AAPL"
_REGIME_TOKEN = {"bullish": "bull", "neutral": "neutral", "bearish": "bear"}


def _count(session: Session, model: Any, run_id: str | None) -> int:
    stmt = select(func.count()).select_from(model)
    if run_id is not None:
        stmt = stmt.where(model.run_id == run_id)
    return int(session.scalar(stmt) or 0)


def status(session: Session, *, provider_name: str | None = None) -> dict[str, Any]:
    """Backend / provider status + the latest live run counts."""
    provider = provider_name or user_settings.read_provider()
    run_id = resolve_active_run_id(session)
    last_scan = session.scalar(
        select(ScanMetadata).order_by(ScanMetadata.pull_timestamp.desc()).limit(1)
    )
    return {
        "backend": "ok",
        "provider_status": "configured" if provider else "missing",
        "current_provider": provider,
        "last_yahoo_request": _iso(market_data_service.last_request_timestamp(session)),
        "last_successful_scan": _iso(last_scan.pull_timestamp) if last_scan else None,
        "current_run_id": run_id,
        "latest_conviction_count": _count(session, ConvictionScore, run_id),
        "latest_analog_count": _count(session, CandidateAnalog, run_id),
        "latest_watchlist_count": _count(session, WatchlistEntryRow, run_id),
        "latest_trade_plan_count": _count(session, TradePlan, run_id),
    }


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True, slots=True)
class Stage:
    name: str
    status: str  # PASS | FAIL
    detail: str
    duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
        }


def _relaxed_scanner() -> MomentumScanner:
    """All gates open so any liquid symbol becomes a candidate (verify engines,
    not the momentum filters)."""
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(
                min_price=0.0,
                min_dollar_volume=0.0,
                min_relative_volume=0.0,
                max_distance_from_ath=1.0,
                require_ema_fast_above_mid=False,
                require_ema_mid_above_slow=False,
                min_sector_rs=0.0,
            )
        )
    )


def verify_pipeline(
    session: Session,
    *,
    provider: MarketDataProvider,
    symbol: str = DEFAULT_VERIFY_SYMBOL,
    provider_name: str = "unknown",
    lookback_days: int = 400,
) -> dict[str, Any]:
    """Run one live symbol through the real engines, PASS/FAIL per stage."""
    sym = symbol.upper()
    stages: list[Stage] = []

    def run(name: str, fn: Any) -> Any:
        started = time.perf_counter()
        try:
            value, detail = fn()
            stages.append(Stage(name, "PASS", detail, _ms(started)))
            return value
        except Exception as exc:  # noqa: BLE001 - any failure is a stage FAIL, reported
            stages.append(Stage(name, "FAIL", f"{type(exc).__name__}: {exc}", _ms(started)))
            return None

    # 1. Pull one live symbol.
    def pull() -> tuple[Any, str]:
        end = to_utc_timestamp(dt.date.today())
        frame = provider.get_bars(sym, end - pd.Timedelta(days=lookback_days), end, Timeframe.DAY)
        if frame is None or frame.empty:
            raise RuntimeError(f"provider {provider_name!r} returned no bars for {sym}")
        return frame, f"{len(frame)} bars, newest {pd.Timestamp(frame.index[-1]).date()}"

    frame = run("pull_live_symbol", pull)
    if frame is None:
        return _result(sym, provider_name, stages)

    # 2. Scan features → candidate (relaxed gates so the symbol always qualifies).
    def scan() -> tuple[Any, str]:
        result = _relaxed_scanner().scan({sym: frame}, sectors={sym: "Technology"})
        cands = result.candidates
        if not cands:
            raise RuntimeError("no candidate produced from features")
        return cands[0], f"price={cands[0].price:.2f} atr={cands[0].atr}"

    candidate = run("compute_features", scan)
    if candidate is None:
        return _result(sym, provider_name, stages)

    # 3. Conviction.
    def conviction() -> tuple[Any, str]:
        inputs = ConvictionInputs(
            market_regime="neutral",
            sector_strength=candidate.sector_rs,
            relative_volume=candidate.relative_volume,
            distance_to_ath=abs(candidate.distance_from_ath),
            momentum_score=candidate.momentum_score / 100.0,
        )
        res = ConvictionEngine().score(inputs)
        if not (0.0 <= res.score <= 100.0):
            raise RuntimeError(f"score out of range: {res.score}")
        return res, f"score={res.score:.0f} band={res.band.value}"

    conv = run("conviction", conviction)

    # 4. Analog cohort (from real closed-trade history; empty cohort still PASSes).
    def analog() -> tuple[Any, str]:
        cohort = [
            t
            for t in TradeRepository(session).analytics_trades(None)
            if t.sector == candidate.sector
        ]
        size = len(cohort)
        if cohort:
            _ = compute_trade_stats(cohort)
        return size, f"sample_size={size} (cohort from real trade history)"

    run("analog", analog)

    # 5. Trade plan.
    def trade_plan() -> tuple[Any, str]:
        plan = TradePlanEngine().plan(
            TradePlanInputs(
                symbol=sym,
                price=candidate.price,
                atr=candidate.atr,
                ema_fast=candidate.ema_fast,
                ema_mid=candidate.ema_mid,
                ema_slow=candidate.ema_slow,
                distance_from_ath=candidate.distance_from_ath,
                relative_volume=candidate.relative_volume,
                sector=candidate.sector,
                conviction_score=conv.score if conv else None,
                conviction_band=conv.band.value if conv else None,
                regime="neutral",
                equity=100_000.0,
            )
        )
        if plan is None:
            raise RuntimeError("no plan (missing price/ATR)")
        return plan, f"entry={plan.entry:.2f} stop={plan.stop:.2f}"

    run("trade_plan", trade_plan)

    # 6. Watchlist.
    def watchlist() -> tuple[Any, str]:
        wc = WatchlistCandidate(
            symbol=sym,
            base_conviction=conv.score if conv else 50.0,
            band=conv.band.value if conv else None,
            factors=conv.normalized_map() if conv else {},
            sector=candidate.sector,
            price=candidate.price,
            atr=candidate.atr,
        )
        produced = WatchlistEngine().generate([wc], as_of=dt.date.today())
        total = sum(len(v) for v in produced.values())
        if total == 0:
            raise RuntimeError("no watchlist entries produced")
        return produced, f"{total} entries across {len(produced)} horizons"

    run("watchlist", watchlist)

    return _result(sym, provider_name, stages)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)


def _result(symbol: str, provider_name: str, stages: list[Stage]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "provider": provider_name,
        "overall": "PASS" if all(s.status == "PASS" for s in stages) else "FAIL",
        "stages": [s.to_dict() for s in stages],
    }
