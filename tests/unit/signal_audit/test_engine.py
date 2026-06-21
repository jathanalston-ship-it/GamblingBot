"""Tests for the pure signal-validation audit engine."""

from __future__ import annotations

import datetime as dt

import numpy as np

from momentum.signal_audit import CandidateOutcome, audit, default_config

CFG = default_config()


def _cand(
    i: int,
    conviction: float,
    r: float,
    *,
    rank: int | None = None,
    eligible: bool | None = None,
    reco: bool | None = None,
    factors: dict[str, float] | None = None,
) -> CandidateOutcome:
    return CandidateOutcome(
        symbol=f"S{i}",
        as_of=dt.date(2024, 1, 1) + dt.timedelta(days=i),
        conviction=conviction,
        conviction_band=None,
        factors=factors or {"momentum_score": conviction / 100.0},
        watchlist_rank=rank,
        eligible=eligible,
        eligibility_confidence=conviction if eligible is not None else None,
        options_recommended=reco,
        r_multiple=r,
        return_pct=r * 0.01,
        mfe=abs(r) + 0.5 if r > 0 else 0.2,
        mae=-0.5,
        exit_reason="target" if r > 0 else "stop",
        holding_days=10,
    )


def _skillful(n: int = 80, seed: int = 3) -> list[CandidateOutcome]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        conv = float(rng.uniform(20, 95))
        r = float((conv - 55) / 30.0 + rng.normal(0, 1.2))
        out.append(_cand(i, conv, r, rank=int(rng.integers(1, 20))))
    return out


def _noise(n: int = 80, seed: int = 9) -> list[CandidateOutcome]:
    rng = np.random.default_rng(seed)
    return [_cand(i, float(rng.uniform(20, 95)), float(rng.normal(0, 1.5))) for i in range(n)]


def test_headline_metrics_and_drawdown():
    rep = audit(_skillful(), CFG)
    assert rep.n_candidates == 80
    assert 0.0 <= rep.win_rate <= 1.0
    assert rep.max_drawdown_r >= 0.0
    assert rep.avg_reward_risk is not None
    # five conviction buckets always present
    assert len(rep.conviction_buckets) == 5


def test_detects_significant_conviction_and_recommends():
    rep = audit(_skillful(), CFG)
    assert rep.calibration.ic is not None and rep.calibration.ic > 0
    assert rep.calibration.p_value is not None and rep.calibration.p_value < 0.05
    names = [f.name for f in rep.strongest_factors]
    assert "Conviction score" in names
    conv_area = next(a for a in rep.areas if a.area == "conviction")
    assert conv_area.significant is True
    assert any(
        "Conviction is a statistically significant predictor" in r for r in rep.recommendations
    )


def test_noise_yields_no_recommendations():
    rep = audit(_noise(), CFG)
    assert rep.strongest_factors == ()
    assert len(rep.recommendations) == 1
    assert "No relationship reached significance" in rep.recommendations[0]
    conv_area = next(a for a in rep.areas if a.area == "conviction")
    assert conv_area.significant is False


def test_eligibility_area_compares_groups():
    rng = np.random.default_rng(5)
    cands = []
    for i in range(60):
        eligible = i % 2 == 0
        # eligible names do clearly better
        r = float(rng.normal(1.2 if eligible else -0.3, 0.8))
        cands.append(_cand(i, 70.0, r, eligible=eligible))
    rep = audit(cands, CFG)
    elig = next(a for a in rep.areas if a.area == "eligibility")
    assert elig.significant is True
    assert any("eligible setups significantly outperformed" in r for r in rep.recommendations)


def test_small_sample_adds_caveat_and_no_conclusions():
    rep = audit(_skillful(n=8), CFG)
    assert any("below the" in c for c in rep.caveats)
    # n below min_sample => conviction can't be declared significant
    assert all(not f.significant for f in rep.factor_scores)


def test_weakest_factors_are_non_significant_lowest_ic():
    rep = audit(_noise(), CFG)
    assert rep.weakest_factors  # populated
    assert all(not f.significant for f in rep.weakest_factors)
