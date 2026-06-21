"""Signal-validation audit (pure logic).

Grades a list of :class:`CandidateOutcome` (predictions joined to realised trade
outcomes) across the platform's six predictive surfaces — conviction, watchlist
ranking, trade-plan targets, stop losses, options recommendations and the
eligibility gate — and emits win-rate/EV-by-conviction-bucket, a calibration
report, ranked predictive factors, a max drawdown and an average reward:risk.

Every conclusion is gated on evidence: a recommendation is only emitted when its
test is significant at ``alpha`` with a sufficient sample. With no significant
signal the audit says so rather than inventing a conclusion.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from momentum.analytics import statistics as st
from momentum.analytics.significance import (
    CorrelationResult,
    TTestResult,
    max_drawdown,
    pearson_with_p,
    welch_ttest,
)
from momentum.signal_audit.config import SignalAuditConfig
from momentum.signal_audit.types import (
    AreaEffectiveness,
    CalibrationReport,
    CandidateOutcome,
    ConvictionBucketStat,
    FactorScore,
    SignalAuditReport,
)

# Conviction sub-factors we expect on a candidate (others are still picked up).
_FACTOR_LABELS = {
    "conviction": "Conviction score",
    "watchlist_rank": "Watchlist rank",
    "eligibility_confidence": "Eligibility confidence",
    "market_regime": "Market regime",
    "sector_strength": "Sector strength",
    "relative_volume": "Relative volume",
    "distance_to_ath": "Distance to ATH",
    "trend_strength": "Trend strength",
    "breadth": "Breadth",
    "momentum_score": "Momentum score",
    "historical_edge": "Historical analogs",
}


def _mean(values: Sequence[float]) -> float | None:
    return float(np.mean(values)) if values else None


def audit(candidates: Sequence[CandidateOutcome], cfg: SignalAuditConfig) -> SignalAuditReport:
    """Run the full validation audit over the candidate outcomes."""
    cands = list(candidates)
    n = len(cands)
    r_all = [c.r_multiple for c in cands]

    win_rate = float(np.mean([1.0 if c.won else 0.0 for c in cands])) if cands else 0.0
    expectancy_r = float(np.mean(r_all)) if r_all else 0.0
    rr = [
        c.mfe / abs(c.mae) for c in cands if c.mfe is not None and c.mae is not None and c.mae < 0
    ]
    avg_reward_risk = _mean(rr)
    payoff = st.payoff_ratio(r_all) if r_all else None
    ordered = sorted(cands, key=lambda c: c.as_of)
    mdd = max_drawdown([c.r_multiple for c in ordered])

    factor_values = _factor_matrix(cands)
    factor_scores = _score_factors(factor_values, r_all_by_candidate=cands, cfg=cfg)
    buckets = _conviction_buckets(cands, cfg)
    calibration = _calibration(cands, buckets, factor_scores)
    areas = _areas(cands, cfg)

    strongest = tuple(
        sorted(
            (f for f in factor_scores if f.significant),
            key=lambda f: abs(f.ic or 0.0),
            reverse=True,
        )
    )
    eligible_factors = [f for f in factor_scores if f.ic is not None and f.n >= cfg.min_sample]
    weakest = tuple(
        sorted((f for f in eligible_factors if not f.significant), key=lambda f: abs(f.ic or 0.0))[
            :5
        ]
    )

    n_conv = sum(1 for c in cands if c.conviction is not None)
    recommendations = _recommendations(areas, strongest, cfg, n)
    caveats = _caveats(cfg, n)

    return SignalAuditReport(
        n_candidates=n,
        n_with_conviction=n_conv,
        win_rate=win_rate,
        expectancy_r=expectancy_r,
        avg_reward_risk=avg_reward_risk,
        payoff_ratio=payoff,
        max_drawdown_r=mdd,
        conviction_buckets=buckets,
        calibration=calibration,
        factor_scores=tuple(factor_scores),
        strongest_factors=strongest,
        weakest_factors=weakest,
        areas=areas,
        recommendations=recommendations,
        caveats=caveats,
        config_hash=cfg.config_hash(),
    )


# --------------------------------------------------------------------------- #
# factors
# --------------------------------------------------------------------------- #
def _factor_matrix(cands: Sequence[CandidateOutcome]) -> dict[str, list[tuple[int, float]]]:
    """Map factor name -> [(candidate index, value)] for every present numeric value."""
    out: dict[str, list[tuple[int, float]]] = {}
    for i, c in enumerate(cands):
        if c.conviction is not None:
            out.setdefault("conviction", []).append((i, c.conviction))
        if c.watchlist_rank is not None:
            # encode so a *higher* factor means a *better* (lower) rank
            out.setdefault("watchlist_rank", []).append((i, float(-c.watchlist_rank)))
        if c.eligibility_confidence is not None:
            out.setdefault("eligibility_confidence", []).append((i, c.eligibility_confidence))
        for name, value in c.factors.items():
            out.setdefault(name, []).append((i, float(value)))
    return out


def _score_factors(
    factor_values: dict[str, list[tuple[int, float]]],
    *,
    r_all_by_candidate: Sequence[CandidateOutcome],
    cfg: SignalAuditConfig,
) -> list[FactorScore]:
    scores: list[FactorScore] = []
    for name, pairs in factor_values.items():
        xs = [v for _, v in pairs]
        ys = [r_all_by_candidate[i].r_multiple for i, _ in pairs]
        corr = pearson_with_p(xs, ys)
        significant = (
            corr.p_value is not None and corr.p_value < cfg.alpha and corr.n >= cfg.min_sample
        )
        direction = "none"
        if significant and corr.r is not None:
            direction = "positive" if corr.r > 0 else "negative"
        scores.append(
            FactorScore(
                name=_FACTOR_LABELS.get(name, name),
                ic=corr.r,
                p_value=corr.p_value,
                n=corr.n,
                significant=significant,
                direction=direction,
            )
        )
    return sorted(scores, key=lambda f: abs(f.ic or 0.0), reverse=True)


# --------------------------------------------------------------------------- #
# conviction buckets + calibration
# --------------------------------------------------------------------------- #
def _conviction_buckets(
    cands: Sequence[CandidateOutcome], cfg: SignalAuditConfig
) -> tuple[ConvictionBucketStat, ...]:
    rated = [c for c in cands if c.conviction is not None]
    out: list[ConvictionBucketStat] = []
    for lo, hi in cfg.conviction_buckets:
        members = [
            c
            for c in rated
            if c.conviction is not None
            and ((lo <= c.conviction < hi) or (hi >= 100 and c.conviction == 100))
        ]
        if not members:
            out.append(ConvictionBucketStat(f"{lo:.0f}-{hi:.0f}", lo, hi, 0, 0.0, 0.0, 0.0))
            continue
        conv = [c.conviction for c in members if c.conviction is not None]
        out.append(
            ConvictionBucketStat(
                label=f"{lo:.0f}-{hi:.0f}",
                lo=lo,
                hi=hi,
                n=len(members),
                win_rate=float(np.mean([1.0 if c.won else 0.0 for c in members])),
                expected_value_r=float(np.mean([c.r_multiple for c in members])),
                avg_predicted=float(np.mean(conv)) / 100.0,
            )
        )
    return tuple(out)


def _calibration(
    cands: Sequence[CandidateOutcome],
    buckets: tuple[ConvictionBucketStat, ...],
    factor_scores: Sequence[FactorScore],
) -> CalibrationReport:
    pairs = [(c.conviction, c.won) for c in cands if c.conviction is not None]
    brier: float | None = None
    if pairs:
        brier = float(np.mean([(conv / 100.0 - (1.0 if won else 0.0)) ** 2 for conv, won in pairs]))
    populated = [b for b in buckets if b.n > 0]
    rates = [b.win_rate for b in populated]
    monotonic = all(rates[i] <= rates[i + 1] + 1e-9 for i in range(len(rates) - 1))
    conv_factor = next((f for f in factor_scores if f.name == _FACTOR_LABELS["conviction"]), None)
    return CalibrationReport(
        buckets=buckets,
        brier_score=brier,
        monotonic_win_rate=monotonic,
        ic=conv_factor.ic if conv_factor else None,
        p_value=conv_factor.p_value if conv_factor else None,
    )


# --------------------------------------------------------------------------- #
# per-area effectiveness
# --------------------------------------------------------------------------- #
def _corr_area(
    area: str, label: str, corr: CorrelationResult, cfg: SignalAuditConfig
) -> AreaEffectiveness:
    significant = corr.p_value is not None and corr.p_value < cfg.alpha and corr.n >= cfg.min_sample
    if corr.r is None:
        headline = f"{label}: insufficient data (n={corr.n})."
    elif significant:
        verb = "predicts" if corr.r > 0 else "inversely predicts"
        headline = f"{label} {verb} outcome (IC={corr.r:.2f}, p={corr.p_value:.3f}, n={corr.n})."
    else:
        headline = f"{label}: no significant relationship (IC={corr.r:.2f}, n={corr.n})."
    return AreaEffectiveness(
        area=area,
        headline=headline,
        metrics={"ic": corr.r, "n": float(corr.n)},
        p_value=corr.p_value,
        significant=significant,
    )


def _ttest_area(
    area: str, label: str, tt: TTestResult, cfg: SignalAuditConfig
) -> AreaEffectiveness:
    enough = tt.n_a >= cfg.min_group and tt.n_b >= cfg.min_group
    significant = enough and tt.p_value is not None and tt.p_value < cfg.alpha
    if tt.p_value is None or not enough:
        headline = f"{label}: insufficient data (n={tt.n_a} vs {tt.n_b})."
    elif significant:
        better = "higher" if tt.diff > 0 else "lower"
        headline = (
            f"{label}: flagged group had {better} R by {tt.diff:+.2f} "
            f"(p={tt.p_value:.3f}, n={tt.n_a} vs {tt.n_b})."
        )
    else:
        headline = (
            f"{label}: no significant difference (Δ={tt.diff:+.2f}, "
            f"p={tt.p_value:.3f}, n={tt.n_a} vs {tt.n_b})."
        )
    return AreaEffectiveness(
        area=area,
        headline=headline,
        metrics={
            "mean_flagged": tt.mean_a,
            "mean_other": tt.mean_b,
            "diff": tt.diff,
            "n_flagged": float(tt.n_a),
            "n_other": float(tt.n_b),
        },
        p_value=tt.p_value,
        significant=significant,
    )


def _areas(
    cands: Sequence[CandidateOutcome], cfg: SignalAuditConfig
) -> tuple[AreaEffectiveness, ...]:
    out: list[AreaEffectiveness] = []

    # 1. conviction vs outcome
    conv = [(c.conviction, c.r_multiple) for c in cands if c.conviction is not None]
    out.append(
        _corr_area(
            "conviction",
            "Conviction score",
            pearson_with_p([a for a, _ in conv], [b for _, b in conv]),
            cfg,
        )
    )

    # 2. watchlist ranking vs outcome (encode so positive IC = better ranks did better)
    wl = [(-c.watchlist_rank, c.r_multiple) for c in cands if c.watchlist_rank is not None]
    out.append(
        _corr_area(
            "watchlist_ranking",
            "Watchlist ranking",
            pearson_with_p([a for a, _ in wl], [b for _, b in wl]),
            cfg,
        )
    )

    # 3. trade-plan target accuracy (descriptive)
    with_mfe = [c for c in cands if c.mfe is not None]
    target_hit_rate = _mean(
        [1.0 if (c.mfe is not None and c.mfe >= cfg.target_r) else 0.0 for c in with_mfe]
    )
    exit_target_rate = _mean([1.0 if c.exit_reason == "target" else 0.0 for c in cands])
    out.append(
        AreaEffectiveness(
            area="trade_plan_targets",
            headline=(
                f"{(target_hit_rate or 0.0) * 100:.0f}% reached the {cfg.target_r:.0f}R target tier "
                f"(MFE); {(exit_target_rate or 0.0) * 100:.0f}% exited at target."
                if with_mfe
                else "Trade-plan targets: no excursion data."
            ),
            metrics={
                "target_hit_rate": target_hit_rate,
                "exit_target_rate": exit_target_rate,
                "avg_mfe_r": _mean([c.mfe for c in with_mfe if c.mfe is not None]),
            },
            p_value=None,
            significant=False,
        )
    )

    # 4. stop-loss effectiveness (descriptive)
    losers = [c for c in cands if c.r_multiple < 0]
    avg_loser_r = _mean([c.r_multiple for c in losers])
    overrun_rate = _mean([1.0 if c.r_multiple <= cfg.stop_overrun_r else 0.0 for c in losers])
    out.append(
        AreaEffectiveness(
            area="stop_loss",
            headline=(
                f"Avg loss {(avg_loser_r or 0.0):.2f}R; "
                f"{(overrun_rate or 0.0) * 100:.0f}% overran past {cfg.stop_overrun_r:.1f}R."
                if losers
                else "Stop-loss: no losing trades in the sample."
            ),
            metrics={
                "avg_loser_r": avg_loser_r,
                "stop_overrun_rate": overrun_rate,
                "stop_exit_rate": _mean([1.0 if c.exit_reason == "stop" else 0.0 for c in cands]),
            },
            p_value=None,
            significant=False,
        )
    )

    # 5. options-recommendation effectiveness (recommended vs not)
    reco = [c.r_multiple for c in cands if c.options_recommended is True]
    no_reco = [c.r_multiple for c in cands if c.options_recommended is False]
    out.append(
        _ttest_area(
            "options_recommendation",
            "Options-recommended setups",
            welch_ttest(reco, no_reco),
            cfg,
        )
    )

    # 6. eligibility-gate effectiveness (eligible vs shares-preferred)
    elig = [c.r_multiple for c in cands if c.eligible is True]
    shares = [c.r_multiple for c in cands if c.eligible is False]
    out.append(
        _ttest_area(
            "eligibility",
            "Options-eligible setups",
            welch_ttest(elig, shares),
            cfg,
        )
    )
    return tuple(out)


# --------------------------------------------------------------------------- #
# recommendations + caveats (evidence-gated)
# --------------------------------------------------------------------------- #
def _recommendations(
    areas: Sequence[AreaEffectiveness],
    strongest: Sequence[FactorScore],
    cfg: SignalAuditConfig,
    n: int,
) -> tuple[str, ...]:
    recs: list[str] = []
    by_area = {a.area: a for a in areas}

    def _area_rec(area: str, positive_msg: str, negative_msg: str) -> None:
        a = by_area.get(area)
        if a is None or not a.significant:
            return
        ic = a.metrics.get("ic")
        diff = a.metrics.get("diff")
        signal = ic if ic is not None else diff
        if signal is None:
            return
        recs.append(positive_msg if signal > 0 else negative_msg)

    _area_rec(
        "conviction",
        "Conviction is a statistically significant predictor — keep it central and "
        "consider increasing its weight.",
        "Conviction is significantly INVERSELY related to outcome — investigate the "
        "scoring before trusting it.",
    )
    _area_rec(
        "watchlist_ranking",
        "Watchlist rank is a significant predictor — higher-ranked names did better; "
        "the ranking is doing real work.",
        "Watchlist rank is significantly inverted — better-ranked names did worse; "
        "review the ranking weights.",
    )
    _area_rec(
        "eligibility",
        "Options-eligible setups significantly outperformed shares-preferred ones — "
        "the eligibility gate adds value.",
        "Options-eligible setups significantly UNDERperformed — the eligibility gate "
        "may be miscalibrated.",
    )
    _area_rec(
        "options_recommendation",
        "Options-recommended setups significantly outperformed — the recommendation "
        "engine is selective in the right direction.",
        "Options-recommended setups significantly underperformed — re-examine the "
        "recommendation criteria.",
    )

    for f in strongest:
        if f.name == _FACTOR_LABELS["conviction"]:
            continue  # already covered by the conviction area
        if f.direction == "positive":
            recs.append(
                f"Factor '{f.name}' is a significant positive predictor "
                f"(IC={f.ic:.2f}, p={f.p_value:.3f}) — consider increasing its weight."
            )
        elif f.direction == "negative":
            recs.append(
                f"Factor '{f.name}' is a significant NEGATIVE predictor "
                f"(IC={f.ic:.2f}, p={f.p_value:.3f}) — consider reducing or inverting its weight."
            )

    if not recs:
        recs.append(
            f"No relationship reached significance at α={cfg.alpha:g} (n={n}). "
            "No adjustments are warranted on the current evidence."
        )
    return tuple(recs)


def _caveats(cfg: SignalAuditConfig, n: int) -> tuple[str, ...]:
    out = [
        "Audited candidates are those that produced a closed trade; candidates that "
        "never traded are not represented (survivorship).",
        "Outcome is realised trade R; options-structure P&L is proxied by the underlying "
        "result, not contract pricing.",
        "Prediction context (conviction / watchlist / eligibility) is joined by symbol to "
        "the latest generation, not strictly point-in-time at entry.",
    ]
    if n < cfg.min_sample:
        out.insert(
            0,
            f"Sample (n={n}) is below the {cfg.min_sample}-observation threshold — treat "
            "all findings as indicative only, not conclusive.",
        )
    return tuple(out)
