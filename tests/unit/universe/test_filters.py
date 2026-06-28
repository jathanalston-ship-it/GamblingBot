"""Tests for the composable filter primitives."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from momentum.universe.filters import (
    EmaBullishStack,
    MinDollarVolume,
    MinPrice,
    MinRelativeVolume,
    MinSectorRelativeStrength,
    WithinDistanceOfATH,
    combine,
)


@pytest.fixture
def features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "price": [10.0, 4.0, 50.0, 20.0],
            "dollar_volume": [30e6, 25e6, 5e6, 40e6],
            "relative_volume": [1.5, 2.0, 0.5, 1.0],
            "distance_from_ath": [-0.05, -0.02, -0.40, -0.10],
            "ema_fast": [11, 5, 49, 21],
            "ema_mid": [10, 4, 50, 20],
            "ema_slow": [9, 3, 51, 19],
            "sector_rs": [0.8, 0.6, 0.3, np.nan],
        },
        index=["AAA", "BBB", "CCC", "DDD"],
    )


def test_min_price(features: pd.DataFrame) -> None:
    mask = MinPrice(5.0)(features)
    assert mask.tolist() == [True, False, True, True]


def test_min_dollar_volume(features: pd.DataFrame) -> None:
    mask = MinDollarVolume(20e6)(features)
    assert mask.tolist() == [True, True, False, True]


def test_min_relative_volume(features: pd.DataFrame) -> None:
    mask = MinRelativeVolume(1.0)(features)
    assert mask.tolist() == [True, True, False, True]


def test_within_distance_of_ath(features: pd.DataFrame) -> None:
    mask = WithinDistanceOfATH(0.25)(features)
    assert mask.tolist() == [True, True, False, True]  # CCC is 40% below


def test_ema_bullish_stack(features: pd.DataFrame) -> None:
    mask = EmaBullishStack(True, True)(features)
    # AAA: 11>10>9 ok; BBB 5>4>3 ok; CCC 49<50 fail; DDD 21>20>19 ok
    assert mask.tolist() == [True, True, False, True]


def test_ema_stack_partial(features: pd.DataFrame) -> None:
    mask = EmaBullishStack(require_fast_above_mid=True, require_mid_above_slow=False)(features)
    assert mask.tolist() == [True, True, False, True]


def test_min_sector_rs_passes_nan(features: pd.DataFrame) -> None:
    mask = MinSectorRelativeStrength(0.5)(features)
    # AAA .8 ok; BBB .6 ok; CCC .3 fail; DDD NaN -> not excluded
    assert mask.tolist() == [True, True, False, True]


def test_combine_reports_eliminations(features: pd.DataFrame) -> None:
    report = combine(
        features,
        [MinPrice(5.0), MinDollarVolume(20e6), WithinDistanceOfATH(0.25)],
    )
    assert report.n_in == 4
    assert report.eliminated["min_price"] == 1  # BBB
    assert report.eliminated["min_dollar_volume"] == 1  # CCC
    # AAA and DDD survive
    assert report.passed.loc["AAA"]
    assert report.passed.loc["DDD"]
    assert report.n_out == 2


def test_combine_records_per_symbol_reason(features: pd.DataFrame) -> None:
    report = combine(
        features,
        [MinPrice(5.0), MinDollarVolume(20e6), WithinDistanceOfATH(0.25)],
    )
    # Each rejected symbol is attributed to the FIRST filter that dropped it.
    assert report.reasons["BBB"] == "min_price"
    assert report.reasons["CCC"] == "min_dollar_volume"
    # Survivors are absent from reasons.
    assert "AAA" not in report.reasons
    assert "DDD" not in report.reasons
    # reasons covers exactly the rejected set.
    assert set(report.reasons) == {s for s in features.index if not report.passed.loc[s]}


def test_combine_empty_filters(features: pd.DataFrame) -> None:
    report = combine(features, [])
    assert report.passed.all()
    assert report.reasons == {}
