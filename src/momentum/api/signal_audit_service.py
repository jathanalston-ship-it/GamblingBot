"""Service layer for the signal-validation audit.

Assembles the last N candidates-with-outcomes — closed trades joined to their
prediction context (latest conviction + sub-factors, best watchlist rank, and the
options-eligibility / options-recommendation verdicts derived from the symbol's
scan) — and runs the pure audit engine. Read-only; no persistence.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.schemas import SignalAuditOut
from momentum.options_eligibility import EligibilityInputs, OptionsEligibilityEngine
from momentum.options_recommendation import OptionsRecommendationEngine, RecommendationInputs
from momentum.persistence.models import ConvictionScore, ScanResult, Trade, WatchlistEntryRow
from momentum.signal_audit import CandidateOutcome, SignalAuditConfig, audit, default_config


def _conviction_factors(row: ConvictionScore) -> dict[str, float]:
    mapping: dict[str, float | None] = {
        "market_regime": row.regime_score,
        "sector_strength": row.sector_strength,
        "relative_volume": row.relative_volume,
        "distance_to_ath": row.distance_to_ath,
        "trend_strength": row.trend_strength,
        "breadth": row.breadth,
        "momentum_score": row.momentum_score,
        "historical_edge": row.historical_edge,
    }
    return {k: v for k, v in mapping.items() if v is not None}


def _latest_by_symbol(rows: list[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in rows:
        out.setdefault(r.symbol, r)
    return out


def signal_audit(
    session: Session,
    *,
    run_id: str | None = None,
    limit: int | None = None,
    config: SignalAuditConfig | None = None,
) -> SignalAuditOut:
    """Build and run the audit over the most recent candidates-with-outcomes."""
    cfg = config or default_config()
    n = limit or cfg.lookback_candidates

    tr_stmt = select(Trade).where(Trade.status == "closed")
    if run_id is not None:
        tr_stmt = tr_stmt.where(Trade.run_id == run_id)
    trades = list(session.scalars(tr_stmt.order_by(Trade.entry_ts.desc()).limit(n)))

    conv_stmt = select(ConvictionScore)
    scan_stmt = select(ScanResult)
    wl_stmt = select(WatchlistEntryRow)
    if run_id is not None:
        conv_stmt = conv_stmt.where(ConvictionScore.run_id == run_id)
        scan_stmt = scan_stmt.where(ScanResult.run_id == run_id)
        wl_stmt = wl_stmt.where(WatchlistEntryRow.run_id == run_id)
    conviction = _latest_by_symbol(
        list(session.scalars(conv_stmt.order_by(ConvictionScore.as_of.desc())))
    )
    scans = _latest_by_symbol(list(session.scalars(scan_stmt.order_by(ScanResult.as_of.desc()))))

    best_rank: dict[str, int] = {}
    for w in session.scalars(wl_stmt):
        cur = best_rank.get(w.symbol)
        if cur is None or w.rank < cur:
            best_rank[w.symbol] = w.rank

    regime = services.latest_regime(session)
    regime_label = regime.regime if regime is not None else None

    elig_cache: dict[str, tuple[bool | None, float | None, bool | None]] = {}

    def _derived(symbol: str) -> tuple[bool | None, float | None, bool | None]:
        if symbol in elig_cache:
            return elig_cache[symbol]
        scan = scans.get(symbol)
        result: tuple[bool | None, float | None, bool | None] = (None, None, None)
        if scan is not None and scan.price and scan.price > 0:
            atr_pct = scan.atr / scan.price if scan.atr and scan.atr > 0 else None
            elig = OptionsEligibilityEngine().assess(
                EligibilityInputs(
                    symbol=symbol,
                    price=scan.price,
                    atr_pct=atr_pct,
                    dollar_volume=scan.dollar_volume,
                    regime=regime_label,
                )
            )
            rec = OptionsRecommendationEngine().recommend(
                RecommendationInputs(
                    symbol=symbol,
                    price=scan.price,
                    atr_pct=atr_pct,
                    iv=scan.implied_vol,
                    iv_rank=scan.iv_rank,
                    dollar_volume=scan.dollar_volume,
                    regime=regime_label,
                    setup_eligible=elig.eligible,
                )
            )
            result = (elig.eligible, elig.confidence, rec.recommended)
        elig_cache[symbol] = result
        return result

    candidates: list[CandidateOutcome] = []
    for t in trades:
        if t.r_multiple is None:
            continue
        conv = conviction.get(t.symbol)
        eligible, elig_conf, options_reco = _derived(t.symbol)
        candidates.append(
            CandidateOutcome(
                symbol=t.symbol,
                as_of=t.entry_ts.date(),
                conviction=conv.score if conv is not None else None,
                conviction_band=conv.band if conv is not None else None,
                factors=_conviction_factors(conv) if conv is not None else {},
                watchlist_rank=best_rank.get(t.symbol),
                eligible=eligible,
                eligibility_confidence=elig_conf,
                options_recommended=options_reco,
                r_multiple=t.r_multiple,
                return_pct=t.return_pct,
                mfe=t.mfe,
                mae=t.mae,
                exit_reason=t.exit_reason,
                holding_days=t.holding_days,
            )
        )

    report = audit(candidates, cfg)
    return SignalAuditOut(**_finite(report.to_dict()))


def _finite(payload: dict[str, Any]) -> dict[str, Any]:
    """Null out any non-finite floats before serialization."""

    def clean(value: Any) -> Any:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return {k: clean(v) for k, v in payload.items()}
