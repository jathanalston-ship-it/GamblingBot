"""Tests for the pure signal-evaluation engine."""

from __future__ import annotations

import datetime as dt

from momentum.signaleval import EvaluatedSignal, evaluate, quality

TS = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)


def _sig(
    sid: int,
    *,
    conviction: float | None,
    r: float | None,
    closed: bool = True,
    source: str = "backtest",
    stype: str = "entry",
    mfe: float | None = None,
    mae: float | None = None,
    predicted_move: float | None = None,
    return_pct: float | None = None,
    holding: int | None = 10,
) -> EvaluatedSignal:
    return EvaluatedSignal(
        signal_id=sid,
        symbol="X",
        ts=TS,
        signal_type=stype,
        direction="long",
        source=source,
        strategy="breakout",
        conviction=conviction,
        band=None,
        predicted_move_pct=predicted_move,
        has_trade=r is not None,
        closed=closed and r is not None,
        r_multiple=r,
        return_pct=return_pct,
        mfe=mfe,
        mae=mae,
        holding_days=holding,
        reward_risk=None,
    )


def test_quality_counts_evaluated_only():
    sigs = [
        _sig(1, conviction=80, r=2.0),
        _sig(2, conviction=70, r=-1.0),
        _sig(3, conviction=60, r=None),  # no trade -> counts in n_signals only
    ]
    q = quality(sigs, "overall")
    assert q.n_signals == 3 and q.n_evaluated == 2
    assert q.win_rate == 0.5
    assert q.expectancy_r == 0.5  # (2 + -1) / 2


def test_e_ratio_from_excursions():
    sigs = [
        _sig(1, conviction=80, r=2.0, mfe=3.0, mae=-1.0),
        _sig(2, conviction=70, r=-1.0, mfe=0.5, mae=-1.5),
    ]
    q = quality(sigs, "overall")
    # avg MFE 1.75 / avg |MAE| 1.25 = 1.4
    assert round(q.e_ratio, 2) == 1.4


def test_calibration_and_conviction_accuracy_perfect_predictor():
    # conviction perfectly separates winners from losers
    sigs = []
    for i in range(20):
        conv = 20 + i * 4  # 20..96
        won = conv >= 60
        sigs.append(_sig(i, conviction=float(conv), r=2.0 if won else -1.0))
    rep = evaluate(sigs)
    # buckets are non-decreasing in win rate -> monotonic, AUC 1.0
    assert rep.conviction_accuracy.monotonic_win_rate is True
    assert rep.conviction_accuracy.rank_auc == 1.0
    assert rep.conviction_accuracy.pearson_conviction_r is not None
    assert rep.conviction_accuracy.pearson_conviction_r > 0.8
    # brier improves vs a coin flip
    assert rep.conviction_accuracy.brier_score is not None
    # high-conviction buckets win, low lose
    by_label = {b.label: b for b in rep.calibration}
    assert by_label["80-100"].actual_win_rate == 1.0
    assert by_label["20-40"].actual_win_rate == 0.0


def test_move_accuracy():
    sigs = [
        _sig(1, conviction=80, r=2.0, predicted_move=0.05, return_pct=0.08),
        _sig(2, conviction=70, r=-1.0, predicted_move=0.05, return_pct=-0.01),
    ]
    rep = evaluate(sigs)
    m = rep.move_accuracy
    assert m.n == 2
    assert round(m.mean_predicted, 3) == 0.05
    assert round(m.mean_actual, 3) == 0.035
    assert round(m.mean_abs_error, 3) == 0.045  # (|0.03| + |-0.06|)/2


def test_grouping_by_source_and_type():
    sigs = [
        _sig(1, conviction=80, r=2.0, source="paper"),
        _sig(2, conviction=70, r=2.0, source="backtest"),
        _sig(3, conviction=60, r=-1.0, source="backtest"),
    ]
    rep = evaluate(sigs)
    by_source = {q.key: q for q in rep.by_source}
    assert set(by_source) == {"paper", "backtest"}
    assert by_source["backtest"].n_evaluated == 2
